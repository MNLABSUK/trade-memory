-- Halden & Rook Electrical demo ops_db (fictional)
DROP TABLE IF EXISTS job_sheets; DROP TABLE IF EXISTS invoices; DROP TABLE IF EXISTS jobs;
CREATE TABLE jobs (job_id text PRIMARY KEY, client_code text, client_name text, title text, site_address text,
  lead_electrician text, start_date date, completed_date date, quoted_value_gbp numeric(10,2), po_number text);
CREATE TABLE invoices (invoice_id text PRIMARY KEY, client_code text, client_name text, job_id text REFERENCES jobs,
  issue_date date, due_date date, net_gbp numeric(10,2), vat_gbp numeric(10,2), total_gbp numeric(10,2),
  amount_paid_gbp numeric(10,2), status text, po_number text, notes text);
CREATE TABLE job_sheets (job_sheet_id text PRIMARY KEY, job_id text REFERENCES jobs, visit_date date, sheet_type text,
  electrician text, notes text, snag_status text, snag_closed_date date, photo_ref text, signed_off_by text);
