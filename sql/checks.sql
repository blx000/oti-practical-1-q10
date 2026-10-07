-- Выполнять после python3 scripts/run_lab.py load.
SELECT count(*) AS bronze_customer_rows FROM bronze.lab.customer;
SELECT count(*) AS bronze_orders_rows FROM bronze.lab.orders;
SELECT count(*) AS bronze_lineitem_rows FROM bronze.lab.lineitem;
SELECT count(*) AS bronze_nation_rows FROM bronze.lab.nation;
SELECT count(*) AS silver_customer_rows FROM silver.lab.customer_nation;
SELECT count(*) AS silver_returned_rows FROM silver.lab.returned_items_q4_1993;
SELECT count(*) AS gold_rows FROM gold.lab.q10_top20_customers;
SELECT * FROM gold.lab.q10_top20_customers ORDER BY revenue DESC, custkey;
SELECT snapshot_id, committed_at, operation FROM silver.lab."schema_evolution_demo$snapshots" ORDER BY committed_at;
