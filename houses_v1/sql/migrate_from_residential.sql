BEGIN;
SET LOCAL lock_timeout = '10s';

INSERT INTO houses_listings (id, external_id, source, operation, property_type, title, description, ai_description,
    price_uah, price_usd, price_eur, area, floor, floors_total, rooms, district, city, street, residential_complex,
    metro_station, url, photo_url, photos, commission, agent_type, agent_name, agent_phone, status, comments,
    created_at, updated_at, parsed_at, ai_title, ai_quality_score, data_completeness)
SELECT id, external_id, source, operation, 'Будинок', title, description, ai_description,
    price_uah, price_usd, price_eur, area, floor, floors_total, rooms, district, city, street, residential_complex,
    metro_station, url, photo_url, photos, commission, agent_type, agent_name, agent_phone, status, comments,
    created_at, updated_at, parsed_at, ai_title, ai_quality_score, data_completeness
FROM active_listings WHERE property_type = 'Будинок'
ON CONFLICT (source, external_id) DO NOTHING;

INSERT INTO houses_raw_listings (id, source, operation, external_id, url, fetched_at, http_status, raw_html, raw_json,
    content_hash, parse_status, error_message, retry_count, created_at, updated_at)
SELECT raw.id, raw.source, raw.operation, raw.external_id, raw.url, raw.fetched_at, raw.http_status, raw.raw_html, raw.raw_json,
    raw.content_hash, raw.parse_status, raw.error_message, raw.retry_count, raw.created_at, raw.updated_at
FROM parser_v2_raw_listings raw
WHERE EXISTS (SELECT 1 FROM parser_v2_normalized_listings norm WHERE norm.raw_listing_id=raw.id AND norm.property_type='Будинок')
   OR raw.url ~ '/doma/|/houses-'
ON CONFLICT (source, external_id) DO NOTHING;

INSERT INTO houses_normalized_listings (id, source, operation, external_id, url, property_type, title, description,
    price_uah, price_usd, price_eur, source_price_raw, source_currency, rooms, area, floor, floor_total, agent_type,
    contact_name, contact_phone, commission, residential_complex, city, district, street, metro_station, full_address,
    photo_url, photos, extraction_confidence, is_valid, validation_errors, raw_listing_id, parsed_at, created_at, updated_at)
SELECT id, source, operation, external_id, url, 'Будинок', title, description,
    price_uah, price_usd, price_eur, source_price_raw, source_currency, rooms, area, floor, floor_total, agent_type,
    contact_name, contact_phone, commission, residential_complex, city, district, street, metro_station, full_address,
    photo_url, photos, extraction_confidence, is_valid, validation_errors, raw_listing_id, parsed_at, created_at, updated_at
FROM parser_v2_normalized_listings WHERE property_type='Будинок'
ON CONFLICT (source, external_id) DO NOTHING;

INSERT INTO houses_listing_status_checks SELECT checks.* FROM listing_status_checks checks
JOIN active_listings listing ON listing.id=checks.listing_id WHERE listing.property_type='Будинок'
ON CONFLICT (listing_id) DO NOTHING;
INSERT INTO houses_listing_enrichment_attempts SELECT attempts.* FROM listing_enrichment_attempts attempts
JOIN active_listings listing ON listing.id=attempts.listing_id WHERE listing.property_type='Будинок'
ON CONFLICT (listing_id) DO NOTHING;
INSERT INTO houses_listing_live_enrichment_attempts SELECT attempts.* FROM listing_live_enrichment_attempts attempts
JOIN active_listings listing ON listing.id=attempts.listing_id WHERE listing.property_type='Будинок'
ON CONFLICT (listing_id) DO NOTHING;
INSERT INTO houses_ai_content_rebuilds SELECT rebuilds.* FROM ai_content_rebuilds rebuilds
JOIN active_listings listing ON listing.id=rebuilds.listing_id WHERE listing.property_type='Будинок'
ON CONFLICT (listing_id) DO NOTHING;

DELETE FROM listing_status_checks USING active_listings WHERE listing_status_checks.listing_id=active_listings.id AND active_listings.property_type='Будинок';
DELETE FROM listing_enrichment_attempts USING active_listings WHERE listing_enrichment_attempts.listing_id=active_listings.id AND active_listings.property_type='Будинок';
DELETE FROM listing_live_enrichment_attempts USING active_listings WHERE listing_live_enrichment_attempts.listing_id=active_listings.id AND active_listings.property_type='Будинок';
DELETE FROM ai_content_rebuilds USING active_listings WHERE ai_content_rebuilds.listing_id=active_listings.id AND active_listings.property_type='Будинок';
DELETE FROM active_listings WHERE property_type='Будинок';
DELETE FROM parser_v2_normalized_listings WHERE property_type='Будинок';
DELETE FROM parser_v2_raw_listings raw WHERE EXISTS (SELECT 1 FROM houses_raw_listings house WHERE house.source=raw.source AND house.external_id=raw.external_id);

UPDATE active_listings SET property_type='Квартира' WHERE lower(property_type) IN ('apartment','квартира');
UPDATE parser_v2_normalized_listings SET property_type='Квартира' WHERE lower(property_type) IN ('apartment','квартира');
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='active_listings_apartments_only_check') THEN
        ALTER TABLE active_listings ADD CONSTRAINT active_listings_apartments_only_check CHECK (property_type = 'Квартира');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='parser_v2_normalized_apartments_only_check') THEN
        ALTER TABLE parser_v2_normalized_listings ADD CONSTRAINT parser_v2_normalized_apartments_only_check CHECK (property_type = 'Квартира');
    END IF;
END $$;
SELECT setval(pg_get_serial_sequence('houses_listings','id'), COALESCE((SELECT max(id) FROM houses_listings), 1), true);
SELECT setval(pg_get_serial_sequence('houses_raw_listings','id'), COALESCE((SELECT max(id) FROM houses_raw_listings), 1), true);
SELECT setval(pg_get_serial_sequence('houses_normalized_listings','id'), COALESCE((SELECT max(id) FROM houses_normalized_listings), 1), true);
COMMIT;
