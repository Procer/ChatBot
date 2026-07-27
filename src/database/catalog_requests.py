import logging
import json
import os
from datetime import datetime

from sqlalchemy.orm import Session

from src.database.session import SessionLocal
from src.database.models import CatalogRequest, CatalogSearchLog, ClientSettings, CatalogProduct


def log_catalog_search(client_id: int, thread_id: str, query: str, found: bool, results_count: int = 0,
                        producto_nombre: str = None, producto_sku: str = None):
    """Registra cada consulta al catálogo (encontrada o no), independientemente de si el
    negocio pide datos de contacto antes de responder. Es best-effort: nunca debe interrumpir
    la conversación si falla el guardado."""
    db = SessionLocal()
    try:
        db.add(CatalogSearchLog(
            client_id=client_id,
            thread_id=thread_id,
            query=(query or "")[:255],
            found=found,
            results_count=results_count,
            producto_nombre=producto_nombre,
            producto_sku=producto_sku,
        ))
        db.commit()
    except Exception as e:
        logging.error(f"Error guardando búsqueda de catálogo: {e}")
    finally:
        db.close()


def process_catalog_completion(client_id: int, thread_id: str, topic: str, data: dict, storage_dest: str = 'database'):
    """Guarda consultas y pedidos de catálogo en su propia sección, separada de los
    trámites administrativos (data_submissions / data_proceedings)."""
    is_pedido = str(topic or "").startswith("Pedido: ")
    tipo = "Pedido" if is_pedido else "Consulta"

    logging.info(f"\n[SaaS] GUARDANDO {tipo.upper()} DE CATÁLOGO")
    logging.info(f" - Cliente ID: {client_id}")
    logging.info(f" - Thread ID: {thread_id}")
    logging.info(f" - Topic: {topic}")

    try:
        from src.database.tagging_manager import assign_tag_by_name
        tag_name = "🛒 Pedido de Catálogo" if is_pedido else "🛍️ Consulta de Catálogo"
        assign_tag_by_name(client_id, thread_id, tag_name)
    except Exception as te:
        logging.error(f"[Tagging] Error applying tag in process_catalog_completion: {te}")

    db: Session = SessionLocal()
    pdf_path = None
    try:
        contact_data = {k: v for k, v in data.items() if k not in ("SKU", "Cantidad", "Fecha de Entrega")}

        if is_pedido:
            # El flujo de pedido solo vuelve a pedir Cantidad/Fecha de Entrega, no
            # repite los datos de contacto: los heredamos de la última consulta
            # de este mismo hilo si existe.
            prev = db.query(CatalogRequest).filter_by(client_id=client_id, thread_id=thread_id).order_by(CatalogRequest.id.desc()).first()
            if prev and prev.contact_data:
                try:
                    prev_contact = json.loads(prev.contact_data)
                    prev_contact.update(contact_data)
                    contact_data = prev_contact
                except Exception:
                    pass

        now_str = datetime.now().strftime("%M%S")
        suffix = str(thread_id)[-4:] if thread_id and len(str(thread_id)) >= 4 else "0000"
        tracking = f"CAT-{suffix}-{now_str}"

        if is_pedido:
            producto_nombre = topic.replace("Pedido: ", "", 1)
        else:
            producto_nombre = data.get("Producto de Interés")

        cantidad = None
        if data.get("Cantidad"):
            try:
                cantidad = int(str(data["Cantidad"]).strip())
            except (TypeError, ValueError):
                cantidad = None

        req = CatalogRequest(
            client_id=client_id,
            thread_id=thread_id,
            tracking_number=tracking,
            tipo=tipo,
            producto_nombre=producto_nombre,
            producto_sku=data.get("SKU"),
            cantidad=cantidad,
            fecha_entrega=data.get("Fecha de Entrega"),
            contact_data=json.dumps(contact_data),
            status="Pendiente"
        )
        db.add(req)
        db.commit()
        db.refresh(req)
        logging.info(f" - Registro de catálogo creado: {tracking}")

        if is_pedido and data.get("SKU"):
            pdf_path = _generar_presupuesto_pedido(db, client_id, req, data)
    except Exception as e:
        logging.error(f"Error guardando {tipo} de catálogo: {e}")
    finally:
        db.close()

    return pdf_path


def _generar_presupuesto_pedido(db: Session, client_id: int, req: CatalogRequest, data: dict):
    """Genera el PDF de presupuesto de un único producto (el confirmado en el pedido)
    y guarda la ruta directamente en el registro de catálogo."""
    try:
        settings = db.query(ClientSettings).filter_by(client_id=client_id).first()
        if not settings or not settings.catalog_send_pdf_quote:
            return None

        prod = db.query(CatalogProduct).filter_by(client_id=client_id, sku=data.get("SKU")).first()
        if not prod:
            return None

        cantidad = req.cantidad or 0

        from src.pricing import resolve_unit_price
        precio_unitario = resolve_unit_price(prod.price, prod.price_rules, cantidad)

        producto = {
            "nombre": prod.name,
            "sku": prod.sku,
            "precio_unitario": precio_unitario,
        }
        if prod.custom_attributes:
            producto["atributos_extra"] = prod.custom_attributes
        if cantidad > 0:
            producto["cantidad"] = cantidad
            producto["subtotal"] = round(precio_unitario * cantidad, 2)

        from src.pdf_quotes import generar_pdf_presupuesto
        pdf_path = generar_pdf_presupuesto(client_id, settings, [producto])

        req.pdf_path = pdf_path
        db.commit()
        logging.info(f" - Presupuesto en PDF generado: {pdf_path}")
        return pdf_path
    except Exception as e:
        logging.error(f"Error generando presupuesto de pedido de catálogo: {e}")
        return None
