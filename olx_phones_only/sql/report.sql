SELECT j.status, COUNT(*) AS cnt FROM olx_phone_jobs j GROUP BY 1 ORDER BY 1;

SELECT
    COUNT(*) AS total_jobs,
    COUNT(*) FILTER (WHERE status='done') AS done,
    COUNT(*) FILTER (WHERE status='retry') AS retry,
    COUNT(*) FILTER (WHERE status='failed') AS failed
FROM olx_phone_jobs;

SELECT
    COUNT(*) AS phones_rows,
    COUNT(DISTINCT phone_e164) AS unique_e164,
    COUNT(DISTINCT url_id) AS urls_with_phone
FROM olx_phones;

SELECT
    (SELECT COUNT(*) FROM olx_sheet_urls) AS total_urls,
    (SELECT COUNT(DISTINCT url_id) FROM olx_phones) AS urls_with_phone,
    ROUND(100.0 * (SELECT COUNT(DISTINCT url_id) FROM olx_phones) / NULLIF((SELECT COUNT(*) FROM olx_sheet_urls),0), 2) AS coverage_pct;
