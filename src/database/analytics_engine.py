import logging
import sqlite3
import json
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ANALYTICS_DB = os.path.join(BASE_DIR, "analytics.sqlite")

# Precios aproximados por 1M de tokens (Entrada / Salida) en USD
PRICING = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}

def log_token_usage(thread_id, model, prompt_tokens, completion_tokens):
    """Calcula el costo y registra el uso de tokens."""
    try:
        # Calcular costo
        base_model = "gpt-4o-mini" if "gpt-4" in model.lower() else "gemini-1.5-flash"
        rates = PRICING.get(base_model, PRICING["gemini-1.5-flash"])
        
        cost = ((prompt_tokens / 1_000_000) * rates["input"]) + ((completion_tokens / 1_000_000) * rates["output"])
        
        conn = sqlite3.connect(ANALYTICS_DB)
        cursor = conn.cursor()
        
        # 1. Log detallado
        cursor.execute("""
            INSERT INTO token_usage (thread_id, model, prompt_tokens, completion_tokens, cost_usd)
            VALUES (?, ?, ?, ?, ?)
        """, (thread_id, model, prompt_tokens, completion_tokens, cost))
        
        # 2. Actualizar resumen de sesión
        cursor.execute("""
            INSERT INTO session_analytics (thread_id, total_tokens, total_cost_usd, last_activity)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(thread_id) DO UPDATE SET
                total_tokens = total_tokens + excluded.total_tokens,
                total_cost_usd = total_cost_usd + excluded.total_cost_usd,
                last_activity = CURRENT_TIMESTAMP
        """, (thread_id, (prompt_tokens + completion_tokens), cost))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Analytics Log: {e}")

def log_message(thread_id, role, content, whatsapp_id=None):
    """Guarda el contenido de un mensaje en el historial legible."""
    try:
        conn = sqlite3.connect(ANALYTICS_DB)
        conn.execute("""
            INSERT INTO messages (thread_id, role, content, whatsapp_id)
            VALUES (?, ?, ?, ?)
        """, (thread_id, role, content, whatsapp_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"log_message: {e}")

def mark_human_intervention(thread_id):
    """Marca que esta sesión necesitó un humano (baja la tasa de deflexión)."""
    try:
        conn = sqlite3.connect(ANALYTICS_DB)
        conn.execute("UPDATE session_analytics SET is_deflected = 0 WHERE thread_id = ?", (thread_id,))
        conn.commit(); conn.close()
    except Exception as e:
        logging.warning(f"Error analíticas: {e}")

def update_session_intent(thread_id, intent):
    """Actualiza la intención detectada de la conversación."""
    try:
        conn = sqlite3.connect(ANALYTICS_DB)
        conn.execute("UPDATE session_analytics SET intent = ? WHERE thread_id = ?", (intent, thread_id))
        conn.commit(); conn.close()
    except Exception as e:
        logging.warning(f"Error analíticas: {e}")

def get_dashboard_metrics():
    """Obtiene el resumen para el panel visual, asegurando que todos los campos existan."""
    try:
        conn = sqlite3.connect(ANALYTICS_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 1. Tasa de Deflexión y Sesiones
        cursor.execute("SELECT COUNT(*) as total, SUM(is_deflected) as deflected FROM session_analytics")
        res = cursor.fetchone()
        total_sessions = res['total'] or 0
        deflected_count = res['deflected'] or 0
        deflection_rate = round((deflected_count / total_sessions * 100), 1) if total_sessions > 0 else 0
        
        # 2. Costo Total
        cursor.execute("SELECT SUM(cost_usd) as cost FROM token_usage")
        estimated_cost = round(cursor.fetchone()['cost'] or 0.0, 4)
        
        # 3. Ahorro Estimado (ROI)
        # Asumimos que cada sesión resuelta por IA ahorra ~5 USD de tiempo humano (sueldo, infraestructura, etc.)
        estimated_savings = round(deflected_count * 5.0, 2)
        
        # 4. Distribución por Modelos
        cursor.execute("SELECT model, COUNT(*) as count FROM token_usage GROUP BY model")
        model_distribution = {row['model']: row['count'] for row in cursor.fetchall()}
        if not model_distribution: model_distribution = {"Sin Datos": 0}

        # 5. Distribución por Canal
        cursor.execute("SELECT COUNT(*) FROM session_analytics WHERE thread_id LIKE 'wa_%'")
        wa_count = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM session_analytics WHERE thread_id LIKE 'tg_%'")
        tg_count = cursor.fetchone()[0] or 0
        wc_count = total_sessions - (wa_count + tg_count)
        channel_distribution = {"WhatsApp": wa_count, "Telegram": tg_count, "Webchat": max(0, wc_count)}

        # 6. Top Temas (Intenciones)
        cursor.execute("SELECT intent, COUNT(*) as count FROM session_analytics WHERE intent IS NOT NULL GROUP BY intent ORDER BY count DESC LIMIT 5")
        top_topics = [dict(row) for row in cursor.fetchall()]

        # 7. Datos para el Gráfico (Últimos 7 días de mensajes)
        cursor.execute("""
            SELECT strftime('%m-%d', timestamp) as day, COUNT(*) as count 
            FROM messages 
            WHERE role = 'user'
            GROUP BY day 
            ORDER BY day DESC LIMIT 7
        """)
        rows_msg = cursor.fetchall()[::-1]
        msg_labels = [r['day'] for r in rows_msg] or ["Hoy"]
        msg_data = [r['count'] for r in rows_msg] or [0]

        # 8. Trámites por día (Esto requiere settings.sqlite)
        submissions_per_day = {"labels": ["Hoy"], "data": [0]}
        try:
            conn_s = sqlite3.connect(os.path.join(BASE_DIR, "settings.sqlite"))
            conn_s.row_factory = sqlite3.Row
            cursor_s = conn_s.cursor()
            cursor_s.execute("""
                SELECT strftime('%m-%d', created_at) as day, COUNT(*) as count 
                FROM form_submissions 
                GROUP BY day 
                ORDER BY day DESC LIMIT 7
            """)
            rows_sub = cursor_s.fetchall()[::-1]
            if rows_sub:
                submissions_per_day = {
                    "labels": [r['day'] for r in rows_sub],
                    "data": [r['count'] for r in rows_sub]
                }
            
            # Top Temas Reales (de submissions)
            cursor_s.execute("SELECT topic, COUNT(*) as count FROM form_submissions GROUP BY topic ORDER BY count DESC LIMIT 5")
            top_topics = [dict(row) for row in cursor_s.fetchall()]
            conn_s.close()
        except: pass

        conn.close()
        return {
            "total_sessions": total_sessions,
            "deflection_rate": deflection_rate,
            "estimated_cost": estimated_cost,
            "estimated_savings": estimated_savings,
            "model_distribution": model_distribution,
            "channel_distribution": channel_distribution,
            "top_topics": top_topics,
            "chart_labels": msg_labels,
            "chart_data": msg_data,
            "submissions_per_day": submissions_per_day
        }
    except Exception as e:
        logging.error(f"Analytics Dashboard: {e}")
        return {
            "total_sessions": 0,
            "deflection_rate": 0,
            "estimated_cost": 0,
            "estimated_savings": 0,
            "model_distribution": {"Sin Datos": 0},
            "chart_labels": ["Sin Datos"],
            "chart_data": [0]
        }
