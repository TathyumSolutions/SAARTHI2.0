-- =====================================================================
-- Region-Wise Orders Extension — for databrige_db
-- =====================================================================
-- Adds a region breakdown on top of the existing vbak/vbap sales tables
-- so orders can be sliced by region and joined with material cost data.
-- Run this AFTER db.py has already generated kna1, mara, vbak, vbap.
-- =====================================================================

DROP TABLE IF EXISTS vbak_region CASCADE;

-- Region derived per customer (kna1.country -> region). Adjust the
-- CASE mapping to match your actual kna1.country values.
CREATE TABLE vbak_region (
    sales_document character varying(10) NOT NULL,
    customer_id character varying(10),
    region_code character varying(6),
    order_date date,
    material_id character varying(18),
    order_qty numeric,
    order_value numeric,
    PRIMARY KEY (sales_document, material_id),
    FOREIGN KEY (sales_document) REFERENCES vbak(sales_document),
    FOREIGN KEY (customer_id) REFERENCES kna1(customer_id),
    FOREIGN KEY (material_id) REFERENCES mara(material_id)
);

COMMENT ON TABLE vbak_region IS 'Region-wise sales order breakdown by material, for cost/region analysis';
COMMENT ON COLUMN vbak_region.region_code IS 'Business region code — see region_lookup.xlsx (code_lookup connector) for names';
COMMENT ON COLUMN vbak_region.material_id IS 'Joins to mara.material_id and material_lookup.xlsx for business names/commodity category';
COMMENT ON COLUMN vbak_region.order_value IS 'Order value at time of order — use with material_lookup + live rate API to compute current cost exposure';

-- Populate from existing vbak/vbap, mapping customer country to region.
-- Adjust the country-code list in each WHEN clause to match your kna1 data.
INSERT INTO vbak_region (sales_document, customer_id, region_code, order_date, material_id, order_qty, order_value)
SELECT
    h.sales_document,
    h.customer_id,
    CASE
        WHEN c.country IN ('USA','CAN') THEN 'NA'
        WHEN c.country IN ('DEU','GBR','FRA','ITA','ESP') THEN 'EU'
        WHEN c.country IN ('IND','CHN','JPN','AUS','SGP') THEN 'APAC'
        WHEN c.country IN ('ARE','ZAF','SAU') THEN 'MEA'
        WHEN c.country IN ('BRA','MEX') THEN 'LATAM'
        ELSE 'APAC'  -- default fallback; tune to your actual country distribution
    END AS region_code,
    h.document_date,
    i.material_id,
    i.quantity,
    i.net_value
FROM vbak h
JOIN kna1 c ON c.customer_id = h.customer_id
JOIN vbap i ON i.sales_document = h.sales_document;

-- =====================================================================
-- ON-THE-FLY MATERIAL COST QUERY
-- =====================================================================
-- This is the join pattern the router should use (and you can run
-- directly) to compute current material cost exposure by region:
--
--   vbak_region.material_id  -> material_lookup.xlsx (material_name, commodity_category)
--   material_lookup.commodity_category -> material_rates API (current $/unit)
--   order_qty * current_rate = live cost exposure
--
-- Example (region + material spend, current period):
--
-- SELECT
--     region_code,
--     material_id,
--     SUM(order_qty)   AS total_qty,
--     SUM(order_value) AS booked_value
-- FROM vbak_region
-- WHERE order_date >= CURRENT_DATE - INTERVAL '90 days'
-- GROUP BY region_code, material_id
-- ORDER BY region_code, total_qty DESC;
--
-- Take the material_id results above, look up commodity_category in
-- material_lookup.xlsx, call the material_rates API for that category's
-- current price, and multiply by total_qty for live material cost.

-- =====================================================================
-- VERIFICATION
-- =====================================================================
SELECT region_code, COUNT(*) AS order_lines, SUM(order_value) AS total_value
FROM vbak_region
GROUP BY region_code
ORDER BY total_value DESC;
