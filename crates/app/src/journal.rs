use anyhow::{Result, ensure};
use nc_core::*;
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::{fs::File, path::Path};

pub struct Journal {
    conn: Connection,
    _lock: File,
}
impl Journal {
    pub fn open(home: &Path) -> Result<Self> {
        std::fs::create_dir_all(home)?;
        let lock = std::fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(home.join("worker.lock"))?;
        fs2::FileExt::try_lock_exclusive(&lock)
            .map_err(|_| anyhow::anyhow!("participant worker busy; queue capacity is one"))?;
        let conn = Connection::open(home.join("journal.sqlite"))?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, spec TEXT NOT NULL UNIQUE, state TEXT NOT NULL, report TEXT);
            CREATE TABLE IF NOT EXISTS publications(id TEXT PRIMARY KEY, record TEXT NOT NULL, state TEXT NOT NULL, receipt TEXT);
            CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, record TEXT NOT NULL, provenance TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints(id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS job_events(sequence INTEGER PRIMARY KEY,job_id TEXT NOT NULL,state TEXT NOT NULL,report TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS publication_events(sequence INTEGER PRIMARY KEY,record_id TEXT NOT NULL,state TEXT NOT NULL,receipt TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TRIGGER IF NOT EXISTS job_created AFTER INSERT ON jobs BEGIN
              INSERT INTO job_events(job_id,state,report) VALUES(NEW.id,NEW.state,NEW.report); END;
            CREATE TRIGGER IF NOT EXISTS job_changed AFTER UPDATE OF state,report ON jobs
              WHEN OLD.state IS NOT NEW.state OR OLD.report IS NOT NEW.report BEGIN
              INSERT INTO job_events(job_id,state,report) VALUES(NEW.id,NEW.state,NEW.report); END;
            CREATE TRIGGER IF NOT EXISTS publication_created AFTER INSERT ON publications BEGIN
              INSERT INTO publication_events(record_id,state,receipt) VALUES(NEW.id,NEW.state,NEW.receipt); END;
            CREATE TRIGGER IF NOT EXISTS publication_changed AFTER UPDATE OF state,receipt ON publications
              WHEN OLD.state IS NOT NEW.state OR OLD.receipt IS NOT NEW.receipt BEGIN
              INSERT INTO publication_events(record_id,state,receipt) VALUES(NEW.id,NEW.state,NEW.receipt); END;
            UPDATE jobs SET state='interrupted' WHERE state='running';
            UPDATE publications SET state='unknown' WHERE state='sending';")?;
        Ok(Self { conn, _lock: lock })
    }
    pub fn job(&self, spec: &ContentId) -> Result<Option<ContentId>> {
        let rows: i64 = self
            .conn
            .query_row("SELECT COUNT(*) FROM jobs", [], |r| r.get(0))?;
        ensure!(rows < 10_000, "journal job limit reached");
        self.conn.execute(
            "INSERT OR IGNORE INTO jobs(id,spec,state) VALUES(?1,?2,'pending')",
            params![uuid::Uuid::new_v4().to_string(), spec.to_string()],
        )?;
        let (state, report): (String, Option<String>) = self.conn.query_row(
            "SELECT state,report FROM jobs WHERE spec=?1",
            [spec.to_string()],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )?;
        ensure!(
            state != "interrupted" && state != "unavailable",
            "job interrupted or unavailable; use retry explicitly to start a fresh evaluation process"
        );
        if state == "complete" {
            return Ok(Some(ContentId::try_from(
                report.ok_or_else(|| anyhow::anyhow!("missing report"))?,
            )?));
        }
        self.conn.execute(
            "UPDATE jobs SET state='running' WHERE spec=?1",
            [spec.to_string()],
        )?;
        Ok(None)
    }
    pub fn retry(&self, spec: &ContentId) -> Result<()> {
        self.conn.execute("UPDATE jobs SET state='pending',report=NULL WHERE spec=?1 AND state IN ('interrupted','unavailable')",[spec.to_string()])?;
        Ok(())
    }
    pub fn complete(&self, spec: &ContentId, report: &ContentId, state: &str) -> Result<()> {
        self.conn.execute(
            "UPDATE jobs SET state=?2,report=?3 WHERE spec=?1",
            params![spec.to_string(), state, report.to_string()],
        )?;
        Ok(())
    }
    pub fn record(&self, id: &ContentId, record: &Value, provenance: &str) -> Result<()> {
        self.conn.execute("INSERT INTO records VALUES(?1,?2,?3) ON CONFLICT(id) DO UPDATE SET provenance=excluded.provenance",params![id.to_string(),serde_json::to_string(record)?,provenance])?;
        Ok(())
    }
    pub fn checkpoint(&self, id: &ContentId) -> Result<()> {
        self.conn.execute(
            "INSERT OR IGNORE INTO checkpoints VALUES(?1)",
            [id.to_string()],
        )?;
        Ok(())
    }
    pub fn publication(&self, id: &ContentId, record: &Value) -> Result<String> {
        self.conn.execute(
            "INSERT OR IGNORE INTO publications VALUES(?1,?2,'pending',NULL)",
            params![id.to_string(), serde_json::to_string(record)?],
        )?;
        Ok(self.conn.query_row(
            "SELECT state FROM publications WHERE id=?1",
            [id.to_string()],
            |r| r.get(0),
        )?)
    }
    pub fn publication_state(
        &self,
        id: &ContentId,
        state: &str,
        receipt: Option<&Value>,
    ) -> Result<()> {
        self.conn.execute(
            "UPDATE publications SET state=?2,receipt=?3 WHERE id=?1",
            params![
                id.to_string(),
                state,
                receipt.map(serde_json::to_string).transpose()?
            ],
        )?;
        Ok(())
    }
}

pub fn snapshot(home: &Path) -> Result<Value> {
    let c = Connection::open_with_flags(
        home.join("journal.sqlite"),
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )?;
    let mut result = json!({});
    if home.join("selected.json").exists() {
        result["selected"] =
            serde_json::from_slice(&nc_core::read_bounded(&home.join("selected.json"), 4096)?)?;
    }
    for (table, sql) in [
        (
            "jobs",
            "SELECT id,spec,state,report FROM jobs ORDER BY rowid DESC LIMIT 100",
        ),
        (
            "publications",
            "SELECT id,record,state,receipt FROM publications ORDER BY rowid DESC LIMIT 100",
        ),
        (
            "records",
            "SELECT id,record,provenance FROM records ORDER BY rowid DESC LIMIT 100",
        ),
        (
            "checkpoints",
            "SELECT id FROM checkpoints ORDER BY rowid DESC LIMIT 100",
        ),
        (
            "job_events",
            "SELECT CAST(sequence AS TEXT) AS sequence,job_id,state,report,created_at FROM job_events ORDER BY sequence DESC LIMIT 100",
        ),
        (
            "publication_events",
            "SELECT CAST(sequence AS TEXT) AS sequence,record_id,state,receipt,created_at FROM publication_events ORDER BY sequence DESC LIMIT 100",
        ),
    ] {
        let mut st = c.prepare(sql)?;
        let names: Vec<String> = st.column_names().iter().map(|x| x.to_string()).collect();
        let rows = st
            .query_map([], |r| {
                let mut obj = serde_json::Map::new();
                for (i, name) in names.iter().enumerate() {
                    let val: Option<String> = r.get(i)?;
                    obj.insert(name.clone(), val.map(Value::String).unwrap_or(Value::Null));
                }
                Ok(Value::Object(obj))
            })?
            .collect::<Result<Vec<_>, _>>()?;
        result[table] = json!(rows);
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn recovery_preserves_completed_computation_and_uncertain_publication() {
        let dir = tempfile::tempdir().unwrap();
        let spec = digest(b"spec");
        let interrupted = digest(b"interrupted");
        let report = digest(b"report");
        let record = digest(b"record");
        {
            let j = Journal::open(dir.path()).unwrap();
            assert!(j.job(&spec).unwrap().is_none());
            j.complete(&spec, &report, "complete").unwrap();
            j.job(&interrupted).unwrap();
            j.publication(&record, &json!({"artifact":report})).unwrap();
            j.publication_state(&record, "sending", None).unwrap();
            assert!(Journal::open(dir.path()).is_err());
        }
        let j = Journal::open(dir.path()).unwrap();
        assert_eq!(j.job(&spec).unwrap(), Some(report));
        assert!(j.job(&interrupted).is_err());
        assert_eq!(j.publication(&record, &json!({})).unwrap(), "unknown");
        j.retry(&interrupted).unwrap();
        assert!(j.job(&interrupted).unwrap().is_none());
        let unavailable = digest(b"unavailable");
        let failed_report = digest(b"failed-report");
        j.job(&unavailable).unwrap();
        j.complete(&unavailable, &failed_report, "unavailable")
            .unwrap();
        j.retry(&unavailable).unwrap();
        j.job(&unavailable).unwrap();
        j.complete(&unavailable, &digest(b"retry-report"), "complete")
            .unwrap();
        let history = snapshot(dir.path()).unwrap();
        assert!(
            history["job_events"]
                .as_array()
                .unwrap()
                .iter()
                .any(|e| e["report"] == failed_report.to_string() && e["state"] == "unavailable")
        );
        assert!(
            history["job_events"]
                .as_array()
                .unwrap()
                .iter()
                .any(|e| e["state"] == "interrupted")
        );
        assert!(
            history["jobs"]
                .as_array()
                .unwrap()
                .iter()
                .all(|e| e["id"] != e["spec"])
        );
    }
}
