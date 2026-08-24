-- =====================================================================
-- SAP-Style Schema Extension — Plant, Valuation, Purchasing, Movements
-- =====================================================================
-- Adds 6 more SAP-style tables on top of the existing databrige_db schema
-- (kna1, lfa1, mara, ska1, skb1, vbak, vbap, likp, lips, vbrk, vbrp,
-- bkpf, bseg, vbak_region). Run this AFTER the base schema + data exist.
--
-- New tables:
--   1. t001w  - Plant master
--   2. marc   - Plant data for material (plant-specific material settings)
--   3. mbew   - Material valuation (moving price / standard price — feeds cost calc)
--   4. ekko   - Purchasing document header
--   5. ekpo   - Purchasing document item
--   6. mseg   - Material document / goods movement (combines mkpf+mseg for simplicity)
-- =====================================================================

DROP TABLE IF EXISTS mseg CASCADE;
DROP TABLE IF EXISTS ekpo CASCADE;
DROP TABLE IF EXISTS ekko CASCADE;
DROP TABLE IF EXISTS mbew CASCADE;
DROP TABLE IF EXISTS marc CASCADE;
DROP TABLE IF EXISTS t001w CASCADE;

-- =====================================================================
-- 1. PLANT MASTER
-- =====================================================================
CREATE TABLE t001w (
    plant character varying(4) NOT NULL,
    plant_name character varying(60),
    city character varying(50),
    country character varying(3),
    PRIMARY KEY (plant)
);

COMMENT ON TABLE t001w IS 'Plant master — physical manufacturing/storage locations';
COMMENT ON COLUMN t001w.plant IS 'Plant code, e.g. PL01. Matches plant values used in production_log.xlsx / inventory_snapshot.xlsx once you align formats.';

INSERT INTO t001w (plant, plant_name, city, country) VALUES
    ('PL01', 'Noida Manufacturing Plant', 'Noida', 'IND'),
    ('PL02', 'Delhi Assembly Plant', 'Delhi', 'IND'),
    ('PL03', 'Pune Fabrication Plant', 'Pune', 'IND');

-- =====================================================================
-- 2. PLANT DATA FOR MATERIAL
-- =====================================================================
CREATE TABLE marc (
    material_id character varying(18) NOT NULL,
    plant character varying(4) NOT NULL,
    mrp_type character varying(2),
    reorder_point numeric,
    safety_stock numeric,
    procurement_type character varying(1),  -- 'E' = in-house production, 'F' = external procurement
    PRIMARY KEY (material_id, plant),
    FOREIGN KEY (material_id) REFERENCES mara(material_id),
    FOREIGN KEY (plant) REFERENCES t001w(plant)
);

COMMENT ON TABLE marc IS 'Plant-specific material settings (MRP, reorder point, procurement type)';
COMMENT ON COLUMN marc.procurement_type IS 'E = in-house production, F = external procurement';

INSERT INTO marc (material_id, plant, mrp_type, reorder_point, safety_stock, procurement_type)
SELECT
    m.material_id,
    p.plant,
    (ARRAY['PD','VB','V1'])[floor(random()*3+1)],
    round((random()*400+100)::numeric, 0),
    round((random()*150+50)::numeric, 0),
    (ARRAY['E','F'])[floor(random()*2+1)]
FROM mara m
CROSS JOIN t001w p
WHERE random() < 0.6;  -- not every material is stocked at every plant

-- =====================================================================
-- 3. MATERIAL VALUATION (feeds material cost calculation directly)
-- =====================================================================
CREATE TABLE mbew (
    material_id character varying(18) NOT NULL,
    valuation_area character varying(4) NOT NULL,  -- typically = plant
    price_control character varying(1),  -- 'S' = standard price, 'V' = moving average price
    standard_price numeric,
    moving_avg_price numeric,
    price_unit integer DEFAULT 1,
    currency character varying(3) DEFAULT 'USD',
    last_updated date,
    PRIMARY KEY (material_id, valuation_area),
    FOREIGN KEY (material_id) REFERENCES mara(material_id),
    FOREIGN KEY (valuation_area) REFERENCES t001w(plant)
);

COMMENT ON TABLE mbew IS 'Material valuation — standard/moving average price per material per plant. Use this JOINed with material_lookup.xlsx and live material_rates API to compare booked cost vs current market cost.';
COMMENT ON COLUMN mbew.standard_price IS 'Pre-set standard cost per price_unit, used for planned costing';
COMMENT ON COLUMN mbew.moving_avg_price IS 'Actual weighted average cost per price_unit, updated on goods receipt';

INSERT INTO mbew (material_id, valuation_area, price_control, standard_price, moving_avg_price, price_unit, currency, last_updated)
SELECT
    m.material_id,
    p.plant,
    (ARRAY['S','V'])[floor(random()*2+1)],
    round((random()*450+10)::numeric, 2),
    round((random()*450+10)::numeric, 2),
    1,
    'USD',
    CURRENT_DATE - (floor(random()*60))::int
FROM mara m
CROSS JOIN t001w p
WHERE random() < 0.6;

-- =====================================================================
-- 4. PURCHASING DOCUMENT HEADER
-- =====================================================================
CREATE TABLE ekko (
    purchasing_document character varying(10) NOT NULL,
    vendor_id character varying(10),
    plant character varying(4),
    document_date date,
    currency character varying(3) DEFAULT 'USD',
    PRIMARY KEY (purchasing_document),
    FOREIGN KEY (vendor_id) REFERENCES lfa1(vendor_id),
    FOREIGN KEY (plant) REFERENCES t001w(plant)
);

COMMENT ON TABLE ekko IS 'Purchase order header — procurement of raw materials from vendors';

INSERT INTO ekko (purchasing_document, vendor_id, plant, document_date, currency)
SELECT
    'PO' || LPAD(gs::text, 8, '0'),
    'V' || LPAD((floor(random()*300+1))::text, 4, '0'),
    (ARRAY['PL01','PL02','PL03'])[floor(random()*3+1)],
    CURRENT_DATE - (floor(random()*180))::int,
    (ARRAY['USD','EUR','GBP'])[floor(random()*3+1)]
FROM generate_series(1, 800) AS gs;

-- =====================================================================
-- 5. PURCHASING DOCUMENT ITEM
-- =====================================================================
CREATE TABLE ekpo (
    purchasing_document character varying(10) NOT NULL,
    item_number integer NOT NULL,
    material_id character varying(18),
    order_qty numeric,
    net_price numeric,
    net_value numeric,
    PRIMARY KEY (purchasing_document, item_number),
    FOREIGN KEY (purchasing_document) REFERENCES ekko(purchasing_document),
    FOREIGN KEY (material_id) REFERENCES mara(material_id)
);

COMMENT ON TABLE ekpo IS 'Purchase order line items — what materials were bought, at what price, from which PO';

INSERT INTO ekpo (purchasing_document, item_number, material_id, order_qty, net_price, net_value)
SELECT
    h.purchasing_document,
    item_num,
    m.material_id,
    q.qty,
    p.price,
    round((q.qty * p.price)::numeric, 2)
FROM ekko h
CROSS JOIN generate_series(1, 2) AS item_num
CROSS JOIN LATERAL (
    SELECT material_id FROM mara ORDER BY random() LIMIT 1
) m
CROSS JOIN LATERAL (SELECT round((random()*900+50)::numeric, 0) AS qty) q
CROSS JOIN LATERAL (SELECT round((random()*400+10)::numeric, 2) AS price) p;

-- =====================================================================
-- 6. MATERIAL DOCUMENT / GOODS MOVEMENT
-- =====================================================================
CREATE TABLE mseg (
    material_document character varying(10) NOT NULL,
    item_number integer NOT NULL,
    material_id character varying(18),
    plant character varying(4),
    movement_type character varying(3),  -- 101 = GR from PO, 261 = issue to production, 601 = goods issue for delivery
    quantity numeric,
    posting_date date,
    purchasing_document character varying(10),
    PRIMARY KEY (material_document, item_number),
    FOREIGN KEY (material_id) REFERENCES mara(material_id),
    FOREIGN KEY (plant) REFERENCES t001w(plant)
);

COMMENT ON TABLE mseg IS 'Goods movement history — receipts, issues to production, and shipments per material/plant';
COMMENT ON COLUMN mseg.movement_type IS '101 = goods receipt from PO, 261 = issue to production order, 601 = goods issue for outbound delivery';

INSERT INTO mseg (material_document, item_number, material_id, plant, movement_type, quantity, posting_date, purchasing_document)
SELECT
    'MD' || LPAD(gs::text, 8, '0'),
    1,
    m.material_id,
    m.plant,
    mt.movement_type,
    round((random()*500+10)::numeric, 0),
    CURRENT_DATE - (floor(random()*120))::int,
    CASE WHEN mt.movement_type = '101' THEN
        (SELECT purchasing_document FROM ekko ORDER BY random() LIMIT 1)
    ELSE NULL END
FROM generate_series(1, 1500) AS gs
CROSS JOIN LATERAL (
    SELECT material_id, plant FROM marc ORDER BY random() LIMIT 1
) m
CROSS JOIN LATERAL (
    SELECT (ARRAY['101','261','601'])[floor(random()*3+1)] AS movement_type
) mt;

-- =====================================================================
-- HOW THESE TIE INTO ON-THE-FLY MATERIAL COST
-- =====================================================================
-- mbew gives you a booked standard/moving-average price per material per
-- plant right now, no join needed for a quick number:
--
--   SELECT material_id, valuation_area, standard_price, moving_avg_price
--   FROM mbew WHERE material_id = 'MAT-00007';
--
-- For a full live-vs-booked comparison, join mbew (booked cost) against
-- material_lookup.xlsx (commodity_category) and the material_rates API
-- (current market price) for the same material, and diff them.
--
-- ekpo gives actual historical purchase price paid per material, useful
-- to sanity-check mbew or trend rising input costs over time:
--
--   SELECT material_id, AVG(net_price) AS avg_purchase_price, COUNT(*) AS po_lines
--   FROM ekpo GROUP BY material_id ORDER BY avg_purchase_price DESC;

-- =====================================================================
-- VERIFICATION
-- =====================================================================
SELECT 't001w' AS table_name, COUNT(*) FROM t001w
UNION ALL SELECT 'marc', COUNT(*) FROM marc
UNION ALL SELECT 'mbew', COUNT(*) FROM mbew
UNION ALL SELECT 'ekko', COUNT(*) FROM ekko
UNION ALL SELECT 'ekpo', COUNT(*) FROM ekpo
UNION ALL SELECT 'mseg', COUNT(*) FROM mseg;
