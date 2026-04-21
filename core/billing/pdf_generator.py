from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from decimal import Decimal
from django.conf import settings
import os


class OrderPDFGenerator:
    """Generador de PDFs para órdenes de compra y venta"""
    
    def __init__(self, order, order_type='purchase'):
        """
        Args:
            order: Instancia de PurchaseOrder o SalesOrder
            order_type: 'purchase' o 'sales'
        """
        self.order = order
        self.order_type = order_type
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()
    
    def _setup_custom_styles(self):
        """Configurar estilos personalizados"""
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#223263'),
            spaceAfter=12,
            alignment=TA_CENTER
        ))
        
        self.styles.add(ParagraphStyle(
            name='CustomHeading',
            parent=self.styles['Heading2'],
            fontSize=12,
            textColor=colors.HexColor('#223263'),
            spaceBefore=6,
            spaceAfter=6
        ))
        
        self.styles.add(ParagraphStyle(
            name='SmallText',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#495057')
        ))
    
    def _get_store_logo(self, store):
        """Obtener ruta del logo de la tienda"""
        if store and store.logo:
            try:
                logo_path = os.path.join(settings.MEDIA_ROOT, str(store.logo))
                if os.path.exists(logo_path):
                    return logo_path
            except:
                pass
        return None
    
    def _build_header(self, store):
        """Construir encabezado con logo, datos de la empresa y datos de la orden"""
        
        # Determinar título y datos de la orden
        if self.order_type == 'purchase':
            title = "ORDEN DE COMPRA"
        else:
            title = "ORDEN DE VENTA"
        
        number = f"#{self.order.id:08d}"
        
        # Información de la orden (lado izquierdo)
        order_text = f"""
        <b>Número:</b> {number}<br/>
        <b>Fecha:</b> {self.order.created_at.strftime('%d/%m/%Y')}<br/>
        <b>Estado:</b> {self.order.get_status_display()}
        """
        order_info = Paragraph(order_text, self.styles['Normal'])
        
        # Información de la empresa (lado derecho)
        if not store:
            store_info = Paragraph("", self.styles['Normal'])
        else:
            company_text = f"""
            <b><font size=12>{store.name}</font></b><br/>
            {getattr(store, 'address', '')}<br/>
            {getattr(store, 'city', '')}, {getattr(store, 'state', '')}<br/>
            Tel: {getattr(store, 'phone', 'N/A')}
            """
            store_info = Paragraph(company_text, self.styles['Normal'])
        
        # Logo (si existe, lo agregamos al lado de la info de la empresa)
        logo_element = None
        if store:
            logo_path = self._get_store_logo(store)
            if logo_path:
                try:
                    logo_element = Image(logo_path, width=0.8*inch, height=0.8*inch, kind='proportional')
                except Exception as e:
                    print(f"Error loading logo: {e}")
        
        # Crear una tabla anidada para logo + empresa en el lado derecho
        if logo_element:
            company_data = [[logo_element, store_info]]
            company_table = Table(company_data, colWidths=[1*inch, 2.5*inch])
            company_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (0, 0), 'CENTER'),
                ('ALIGN', (1, 0), (1, 0), 'LEFT'),
                ('VALIGN', (0, 0), (1, 0), 'MIDDLE'),
            ]))
            right_content = company_table
        else:
            right_content = store_info
        
        # Título que abarca todo el ancho
        title_para = Paragraph(f"<b>{title}</b>", self.styles['CustomTitle'])
        
        # Crear tabla: primera fila con título, segunda fila con orden info (izq) y empresa (der)
        header_data = [
            [title_para, ''],
            [order_info, right_content]
        ]
        
        header_table = Table(header_data, colWidths=[3.75*inch, 3.75*inch])
        header_table.setStyle(TableStyle([
            # Título
            ('SPAN', (0, 0), (1, 0)),  # Título abarca ambas columnas
            ('ALIGN', (0, 0), (1, 0), 'CENTER'),
            ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#18c29c')),
            ('TEXTCOLOR', (0, 0), (1, 0), colors.whitesmoke),
            ('FONTSIZE', (0, 0), (1, 0), 14),
            
            # Contenido
            ('ALIGN', (0, 1), (0, 1), 'LEFT'),   # Orden info a la izquierda
            ('ALIGN', (1, 1), (1, 1), 'RIGHT'),  # Empresa a la derecha
            ('VALIGN', (0, 1), (1, 1), 'TOP'),
            
            # Bordes y padding
            ('BOX', (0, 0), (-1, -1), 1.5, colors.grey),
            ('ROUNDEDCORNERS', [10, 10, 10, 10]),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            ('TOPPADDING', (0, 0), (1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (1, 0), 12),
            ('TOPPADDING', (0, 1), (1, 1), 15),
            ('BOTTOMPADDING', (0, 1), (1, 1), 15),
        ]))
        
        return header_table
    
    def _build_counterpart_info(self):
        """Construir cuadro con información de proveedor/cliente (segundo cuadro)"""
        if self.order_type == 'purchase':
            counterpart_label = "Proveedor:"
            counterpart_name = self.order.supplier.name if self.order.supplier else "N/A"
            counterpart_contact = getattr(self.order.supplier, 'contact_name', '') if self.order.supplier else ""
            counterpart_phone = getattr(self.order.supplier, 'phone', '') if self.order.supplier else ""
            counterpart_email = getattr(self.order.supplier, 'email', '') if self.order.supplier else ""
        else:  # sales
            counterpart_label = "Cliente:"
            if self.order.customer:
                counterpart_name = f"{getattr(self.order.customer, 'first_name', '')} {getattr(self.order.customer, 'last_name', '')}".strip()
                if not counterpart_name:
                    counterpart_name = getattr(self.order.customer, 'name', 'Cliente')
            else:
                counterpart_name = "Venta Mostrador"
            counterpart_contact = getattr(self.order.customer, 'email', '') if self.order.customer else ""
            counterpart_phone = getattr(self.order.customer, 'phone', '') if self.order.customer else ""
            counterpart_email = counterpart_contact
        
        # Información del proveedor/cliente
        info_text = f"""
        <b>{counterpart_label}</b> {counterpart_name}<br/>
        <b>Teléfono:</b> {counterpart_phone}<br/>
        <b>Contacto:</b> {counterpart_contact if counterpart_contact else 'N/A'}<br/>
        """
        
        if counterpart_email and counterpart_email != counterpart_contact:
            info_text += f"<b>Email:</b> {counterpart_email}<br/>"
        
        # Crear tabla que ocupe todo el ancho
        counterpart_data = [[Paragraph(info_text, self.styles['Normal'])]]
        
        counterpart_table = Table(counterpart_data, colWidths=[7.5*inch])
        counterpart_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'),
            ('VALIGN', (0, 0), (0, 0), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 1.5, colors.grey),
            ('ROUNDEDCORNERS', [10, 10, 10, 10]),
            ('LEFTPADDING', (0, 0), (-1, -1), 15),
            ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        
        return counterpart_table
    
    def _build_items_table(self):
        """Construir tabla de items"""
        # Encabezados
        data = [['#', 'Artículo', 'Descripción', 'U.Med.', 'Cantidad', 'Precio Unit.', 'Total']]
        
        # Obtener items
        if self.order_type == 'purchase':
            items = self.order.items.all()
        else:  # sales
            items = self.order.sales_items.all()
        
        # Agregar filas de items
        for idx, item in enumerate(items, 1):
            unit_name = item.product_unit.name if item.product_unit else item.product.base_unit_name
            total = Decimal(str(item.quantity)) * item.unit_price
            
            data.append([
                str(idx),
                item.product.sku,
                item.product.description[:40],  # Truncar si es muy largo
                unit_name,
                f"{item.quantity}",
                f"${item.unit_price:,.2f}",
                f"${total:,.2f}"
            ])
        
        # Crear tabla
        table = Table(data, colWidths=[0.4*inch, 1*inch, 2.5*inch, 0.8*inch, 0.8*inch, 1*inch, 1*inch])
        table.setStyle(TableStyle([
            # Encabezado
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#18c29c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            
            # Datos
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # #
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),    # SKU
            ('ALIGN', (2, 1), (2, -1), 'LEFT'),    # Descripción
            ('ALIGN', (3, 1), (3, -1), 'CENTER'),  # U.Med
            ('ALIGN', (4, 1), (4, -1), 'RIGHT'),   # Cantidad
            ('ALIGN', (5, 1), (-1, -1), 'RIGHT'),  # Precios
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        
        return table
    
    def _build_totals_table(self):
        """Construir tabla de totales"""
        subtotal = self.order.total_price - self.order.taxes + self.order.discount - self.order.shipping_cost
        
        data = [
            ['Subtotal:', f"${subtotal:,.2f}"],
            ['Descuento:', f"${self.order.discount:,.2f}"],
            ['IVA (21%):', f"${self.order.taxes:,.2f}"],
        ]
        
        if self.order_type == 'purchase' or self.order.shipping_cost > 0:
            data.append(['Envío:', f"${self.order.shipping_cost:,.2f}"])
        
        data.append(['<b>TOTAL:</b>', f"<b>${self.order.total_price:,.2f}</b>"])
        
        # Convertir a Paragraphs para darle formato
        formatted_data = []
        for row in data:
            formatted_data.append([
                Paragraph(row[0], self.styles['Normal']),
                Paragraph(row[1], self.styles['Normal'])
            ])
        
        table = Table(formatted_data, colWidths=[1.5*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
            ('TOPPADDING', (0, -1), (-1, -1), 10),
        ]))
        
        return table
    
    def _build_footer(self):
        """Construir pie de orden con observaciones y términos"""
        footer_text = f"""
        <b>Observaciones:</b><br/>
        {self.order.description or 'Sin observaciones'}<br/><br/>
        <b>Forma de Pago:</b> {self.order.payment_method}<br/>
        """
        
        if self.order_type == 'purchase':
            footer_text += f"<b>Fecha de Entrega:</b> {self.order.delivery_date.strftime('%d/%m/%Y') if self.order.delivery_date else 'A coordinar'}<br/>"
        else:
            footer_text += f"<b>Fecha de Entrega:</b> {self.order.delivery_date.strftime('%d/%m/%Y') if self.order.delivery_date else 'Retiro en local'}<br/>"
            if self.order.delivery:
                footer_text += f"<b>Entregar en:</b> {self.order.deliver_to}<br/>"
        
        if self.order.transport:
            footer_text += f"<b>Transporte:</b> {self.order.transport}<br/>"
        
        return Paragraph(footer_text, self.styles['SmallText'])
    
    def generate(self, filename):
        """Generar el PDF"""
        doc = SimpleDocTemplate(
            filename,
            pagesize=A4,
            rightMargin=0.35*inch,
            leftMargin=0.35*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch
        )
        
        # Construir elementos del documento
        elements = []
        
        # Obtener tienda de forma segura
        store = None
        try:
            if self.order_type == 'purchase':
                # Para órdenes de compra, intentar obtener store desde created_by
                if self.order.created_by:
                    # Intentar obtener employee relacionado
                    if hasattr(self.order.created_by, 'employee'):
                        store = self.order.created_by.employee.store
            else:
                # Para órdenes de venta, obtener desde employee
                if self.order.employee:
                    store = self.order.employee.store
        except Exception as e:
            print(f"Error getting store: {e}")
            store = None
        
        # Si no se pudo obtener store, usar la primera activa
        if not store:
            try:
                from core.store.models import Store
                store = Store.objects.filter(is_active=True).first()
            except Exception as e:
                print(f"Error getting default store: {e}")
        
        # Header (primer cuadro con empresa, logo y datos de orden)
        header = self._build_header(store)
        if header:
            elements.append(header)
            elements.append(Spacer(1, 0.2*inch))
        
        # Información de proveedor/cliente (segundo cuadro)
        counterpart_info = self._build_counterpart_info()
        elements.append(counterpart_info)
        elements.append(Spacer(1, 0.2*inch))
        
        # Tabla de items
        elements.append(self._build_items_table())
        elements.append(Spacer(1, 0.2*inch))
        
        # Totales (alineados a la derecha)
        totals_table = self._build_totals_table()
        totals_table.hAlign = 'RIGHT'
        elements.append(totals_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Footer
        elements.append(self._build_footer())
        
        # Generar PDF
        doc.build(elements)
        
        return filename
