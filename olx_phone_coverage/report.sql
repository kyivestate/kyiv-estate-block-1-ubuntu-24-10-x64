SELECT
    j.status AS job_status,
    r.coverage_status,
    COUNT(*) AS cnt
FROM olx_sheet_phone_jobs j
LEFT JOIN olx_sheet_phone_results r ON r.job_id = j.id
GROUP BY 1,2
ORDER BY 1,2;

SELECT
    COUNT(*) AS total_jobs,
    COUNT(*) FILTER (WHERE status = 'done') AS done_jobs,
    COUNT(*) FILTER (WHERE status = 'retry') AS retry_jobs,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed_jobs
FROM olx_sheet_phone_jobs;

SELECT
    COUNT(*) AS phones_found,
    COUNT(*) FILTER (WHERE phone_count > 0) AS with_nonempty_phone,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE phone_count > 0) / NULLIF(COUNT(*), 0),
        2
    ) AS coverage_percent
FROM olx_sheet_phone_results;
