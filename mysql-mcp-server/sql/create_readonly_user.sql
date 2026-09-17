-- Run this as a MySQL administrator.
-- Replace values before executing.

CREATE USER 'mcp_reader'@'%' IDENTIFIED BY 'REPLACE_WITH_A_STRONG_PASSWORD';

GRANT SELECT ON `YOUR_DATABASE`.* TO 'mcp_reader'@'%';

FLUSH PRIVILEGES;

-- Verify:
SHOW GRANTS FOR 'mcp_reader'@'%';
