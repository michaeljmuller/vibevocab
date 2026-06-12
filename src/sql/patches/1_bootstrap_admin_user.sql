INSERT INTO users (email, name, is_admin)
VALUES ('mike@themullers.org', 'Michael Muller', TRUE)
ON CONFLICT (email) DO NOTHING;
