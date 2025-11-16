# Armonic

Armonic es una plataforma de apoyo logístico para **pymes restauranteras**.  
El objetivo es ayudarlas a reducir el **costo de producción** (idealmente por debajo del 30% de los ingresos) usando:

- Predicción de demanda
- Gestión inteligente de compras
- Control de entradas de mercadería con OCR + LLM

Todo desde una interfaz simple construida con **Streamlit**.

---

## Módulos principales

### 1. Forecast (Demanda)

- Carga histórico de ventas (`historico_de_ventas_corrected.csv`)
- Muestra:
  - Serie de órdenes diarias vs. estimación.
  - Tabla por producto con:
    - `Q_ESTIMACION`
    - `%_NEGOCIO`
    - `TOTAL`
- Genera insights usando un agente experto en los datos de la pyme a evaluar en base a:
  - Contexto logístico
  - Fecha actual (feriados, patrones estacionales, etc.).

### 2. Facturación (Gestionar compra)

- Sube **facturas / notas de pedido** (`PDF`, `PNG`, `JPG`, `XML`).
- Si es imagen/PDF → usa OCR con `gpt-4o-mini` para extraer:
  - `proveedor, descripcion, cantidad, pu, desc, um`
- Construye tabla **Gestionar compra** por producto:
  - `Q_ESTIMACION`
  - `PRECIO_HISTORICO`
  - `ENTRADAS: CANTIDAD INSUMOS`
  - `PRECIO_MERCADO`
  - `AJUSTE_MERMAS`
  - `MONTO_ESTIMADO`, `PRESUPUESTO`, `MONTO_REAL`, `DIF`
- El usuario puede editar:
  - Q de estimación
  - Proveedor
  - Precio histórico & precio de mercado
  - Entradas y % de mermas
- El resultado se guarda, y pasa al siguiente módulo de **proveedores**.

### 3. Entradas de Mercadería (Proveedores)

- Importa la tabla `entradas_insumos_df` desde `facturas.py`.
- Filtra por `PROVEEDOR`.
- Permite marcar con un checkbox (`INCLUIR`) qué insumos van a presupuesto.
- Calcula métricas:
  - `TOTAL FALTANTE`
  - `VALORIZADO_ENTRANTE` (MONTO_REAL)
  - `VALORIZADO_RESTANTE` (solo DIF positivos)
- Genera insights con LLM:
  - Sobrecostos
  - Riesgo de faltantes
  - Recomendaciones para ajustar compras/cambiar proveedor.
- Botón **“💰 Generar presupuesto”** permite descargar CSV/JSON solo de los insumos seleccionados.
