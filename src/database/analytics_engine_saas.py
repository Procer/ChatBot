import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func

from src.database.session import SessionLocal
from src.database.models import TokenUsage, Message, SessionAnalytics, Submission

PRICING = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}

def log_token_usage(client_id: int, thread_id: str, model: str, prompt_tokens: int, completion_tokens: int):
    """Calcula el costo y registra el uso de tokens para un cliente específico."""
    try:
        base_model = "gpt-4o-mini" if "gpt-4" in model.lower() else "gemini-1.5-flash"
        rates = PRICING.get(base_model, PRICING["gemini-1.5-flash"])
        cost = ((prompt_tokens / 1_000_000) * rates["input"]) + ((completion_tokens / 1_000_000) * rates["output"])
        
        db: Session = SessionLocal()
        
        # 1. Log detallado
        usage = TokenUsage(
            client_id=client_id,
            thread_id=thread_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost
        )
        db.add(usage)
        
        # 2. Actualizar resumen de sesión
        session = db.query(SessionAnalytics).filter_by(client_id=client_id, thread_id=thread_id).first()
        if session:
            session.total_tokens += (prompt_tokens + completion_tokens)
            session.total_cost_usd += cost
            session.last_activity = datetime.utcnow()
        else:
            session = SessionAnalytics(
                client_id=client_id,
                thread_id=thread_id,
                total_tokens=(prompt_tokens + completion_tokens),
                total_cost_usd=cost
            )
            db.add(session)
            
        db.commit()
    except Exception as e:
        logging.error(f"Analytics Log SaaS: {e}")
    finally:
        db.close()

def log_message(client_id: int, thread_id: str, role: str, content: str, whatsapp_id: str = None):
    """Guarda el contenido de un mensaje en el historial legible por cliente."""
    try:
        db: Session = SessionLocal()
        msg = Message(
            client_id=client_id,
            thread_id=thread_id,
            role=role,
            content=content,
            whatsapp_id=whatsapp_id
        )
        db.add(msg)
        db.commit()
    except Exception as e:
        logging.error(f"log_message SaaS: {e}")
    finally:
        db.close()

def mark_human_intervention(client_id: int, thread_id: str):
    """Marca que esta sesión necesitó un humano (baja la tasa de deflexión)."""
    try:
        db: Session = SessionLocal()
        session = db.query(SessionAnalytics).filter_by(client_id=client_id, thread_id=thread_id).first()
        if session:
            session.is_deflected = False
            db.commit()
    except Exception as e:
        logging.warning(f"Error analíticas SaaS (human): {e}")
    finally:
        db.close()

def update_session_intent(client_id: int, thread_id: str, intent: str):
    """Actualiza la intención detectada de la conversación."""
    try:
        db: Session = SessionLocal()
        session = db.query(SessionAnalytics).filter_by(client_id=client_id, thread_id=thread_id).first()
        if session:
            session.intent = intent
            db.commit()
    except Exception as e:
        logging.warning(f"Error analíticas SaaS (intent): {e}")
    finally:
        db.close()

def get_dashboard_metrics(client_id: int):
    """Obtiene el resumen para el panel visual filtrado por cliente SaaS."""
    try:
        db: Session = SessionLocal()
        
        # 1. Tasa de Deflexión y Sesiones
        total_sessions = db.query(SessionAnalytics).filter_by(client_id=client_id).count()
        deflected_count = db.query(SessionAnalytics).filter_by(client_id=client_id, is_deflected=True).count()
        deflection_rate = round((deflected_count / total_sessions * 100), 1) if total_sessions > 0 else 0
        
        # 2. Costo Total
        cost_query = db.query(func.sum(TokenUsage.cost_usd)).filter_by(client_id=client_id).scalar()
        estimated_cost = round(cost_query or 0.0, 4)
        
        # 3. Ahorro Estimado (ROI)
        estimated_savings = round(deflected_count * 5.0, 2)
        
        # 4. Distribución por Modelos
        model_distribution = {}
        for row in db.query(TokenUsage.model, func.count(TokenUsage.id)).filter_by(client_id=client_id).group_by(TokenUsage.model).all():
            model_distribution[row[0]] = row[1]
        if not model_distribution: model_distribution = {"Sin Datos": 0}

        # 5. Distribución por Canal
        wa_count = db.query(SessionAnalytics).filter(SessionAnalytics.client_id == client_id, SessionAnalytics.thread_id.like('%@c.us%')).count()
        tg_count = db.query(SessionAnalytics).filter(
            SessionAnalytics.client_id == client_id,
            ~SessionAnalytics.thread_id.like('%@%'),
            ~SessionAnalytics.thread_id.like('playground%'),
            ~SessionAnalytics.thread_id.like('usuario_nuevo_%')
        ).count()
        
        wc_count = total_sessions - (wa_count + tg_count)
        channel_distribution = {"WhatsApp": wa_count, "Telegram": tg_count, "Webchat": max(0, wc_count)}

        # 6. Top Temas (Intenciones)
        top_topics = []
        for row in db.query(SessionAnalytics.intent, func.count(SessionAnalytics.id)).filter(
            SessionAnalytics.client_id == client_id, 
            SessionAnalytics.intent.isnot(None)
        ).group_by(SessionAnalytics.intent).order_by(func.count(SessionAnalytics.id).desc()).limit(5).all():
            top_topics.append({"intent": row[0], "count": row[1]})

        # 7. Datos para el Gráfico (Últimos 7 días) agrupados en memoria
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        recent_msgs = db.query(Message.timestamp).filter(
            Message.client_id == client_id, 
            Message.role == 'user',
            Message.timestamp >= seven_days_ago
        ).all()
        
        daily_counts = {}
        for msg in recent_msgs:
            if msg[0]:
                day_str = msg[0].strftime('%m-%d')
                daily_counts[day_str] = daily_counts.get(day_str, 0) + 1
            
        if daily_counts:
            sorted_days = sorted(daily_counts.keys())
            msg_labels = sorted_days
            msg_data = [daily_counts[d] for d in sorted_days]
        else:
            msg_labels = ["Hoy"]
            msg_data = [0]

        # 8. Trámites por día
        recent_subs = db.query(Submission.created_at, Submission.topic).filter(
            Submission.client_id == client_id,
            Submission.created_at >= seven_days_ago
        ).all()
        
        sub_counts = {}
        topic_counts = {}
        for sub in recent_subs:
            if sub[0]:
                day_str = sub[0].strftime('%m-%d')
                sub_counts[day_str] = sub_counts.get(day_str, 0) + 1
            if sub[1]:
                topic_counts[sub[1]] = topic_counts.get(sub[1], 0) + 1
                
        if sub_counts:
            sorted_s_days = sorted(sub_counts.keys())
            submissions_per_day = {
                "labels": sorted_s_days,
                "data": [sub_counts[d] for d in sorted_s_days]
            }
        else:
            submissions_per_day = {"labels": ["Hoy"], "data": [0]}
            
        if topic_counts:
            top_topics = [{"intent": k, "count": v} for k, v in sorted(topic_counts.items(), key=lambda item: item[1], reverse=True)[:5]]

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
        logging.error(f"Analytics Dashboard SaaS: {e}")
        return {
            "total_sessions": 0,
            "deflection_rate": 0,
            "estimated_cost": 0,
            "estimated_savings": 0,
            "model_distribution": {"Sin Datos": 0},
            "channel_distribution": {"WhatsApp": 0, "Telegram": 0, "Webchat": 0},
            "top_topics": [],
            "chart_labels": ["Sin Datos"],
            "chart_data": [0],
            "submissions_per_day": {"labels": ["Hoy"], "data": [0]}
        }
    finally:
        db.close()
