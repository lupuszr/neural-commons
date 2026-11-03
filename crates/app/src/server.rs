use anyhow::Result;
use axum::{
    Json, Router,
    extract::{Path, State},
    http::{HeaderMap, StatusCode, header},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
};
use nc_core::*;
use std::{
    path::{Path as FsPath, PathBuf},
    sync::Arc,
};
struct App {
    home: PathBuf,
    store: ArtifactStore,
    token: String,
    permits: Arc<tokio::sync::Semaphore>,
    commands: Arc<tokio::sync::Semaphore>,
}
struct GuardedBytes {
    bytes: Vec<u8>,
    _permit: tokio::sync::OwnedSemaphorePermit,
}
impl AsRef<[u8]> for GuardedBytes {
    fn as_ref(&self) -> &[u8] {
        &self.bytes
    }
}
fn authorized(headers: &HeaderMap, token: &str) -> bool {
    let expected = format!("Bearer {token}");
    let value = headers
        .get(header::AUTHORIZATION)
        .map(|h| h.as_bytes())
        .unwrap_or(&[]);
    value.len() == expected.len()
        && value
            .iter()
            .zip(expected.as_bytes())
            .fold(0u8, |a, (x, y)| a | (x ^ y))
            == 0
}
async fn artifact(
    State(app): State<Arc<App>>,
    Path(raw): Path<String>,
    headers: HeaderMap,
) -> Response {
    if !authorized(&headers, &app.token) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.permits.clone().try_acquire_owned() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    let Ok(id) = ContentId::try_from(raw) else {
        return StatusCode::BAD_REQUEST.into_response();
    };
    match app.store.get(&id) {
        Ok(bytes) => (
            [
                (header::CONTENT_TYPE, "application/octet-stream"),
                (header::CACHE_CONTROL, "no-store"),
                (header::X_CONTENT_TYPE_OPTIONS, "nosniff"),
            ],
            bytes::Bytes::from_owner(GuardedBytes {
                bytes,
                _permit: permit,
            }),
        )
            .into_response(),
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}
async fn state(State(app): State<Arc<App>>, headers: HeaderMap) -> Response {
    if !authorized(&headers, &app.token) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(_permit) = app.permits.try_acquire() else {
        return StatusCode::SERVICE_UNAVAILABLE.into_response();
    };
    match crate::journal::snapshot(&app.home) {
        Ok(v) => Json(v).into_response(),
        Err(_) => (StatusCode::SERVICE_UNAVAILABLE, "Journal unavailable").into_response(),
    }
}

#[derive(serde::Deserialize)]
#[serde(tag = "action", rename_all = "snake_case", deny_unknown_fields)]
enum UserAction {
    Register {
        file: String,
        mapping: Option<String>,
    },
    Put {
        file: String,
    },
    Diff {
        parent: String,
        candidate: String,
    },
    Apply {
        parent: String,
        patch: String,
    },
    Evaluate {
        spec: String,
    },
    Propose {
        spec: String,
    },
    Reproduce {
        record: String,
    },
    Fetch {
        record: String,
    },
    Select {
        checkpoint: String,
    },
    Export {
        checkpoint: String,
        directory: String,
    },
}
async fn action(
    State(app): State<Arc<App>>,
    headers: HeaderMap,
    Json(request): Json<UserAction>,
) -> Response {
    if !authorized(&headers, &app.token) {
        return StatusCode::UNAUTHORIZED.into_response();
    }
    let Ok(permit) = app.commands.clone().try_acquire_owned() else {
        return (
            StatusCode::SERVICE_UNAVAILABLE,
            "Another operation is running",
        )
            .into_response();
    };
    let args = match request {
        UserAction::Register { file, mapping } => {
            let mut a = vec!["register".into(), file];
            if let Some(m) = mapping.filter(|m| !m.is_empty()) {
                a.extend(["--inference-artifacts".into(), m]);
            }
            a
        }
        UserAction::Put { file } => vec!["put".into(), file],
        UserAction::Diff { parent, candidate } => {
            vec!["patch".into(), "diff".into(), parent, candidate]
        }
        UserAction::Apply { parent, patch } => vec!["patch".into(), "apply".into(), parent, patch],
        UserAction::Evaluate { spec } => vec!["evaluate".into(), spec],
        UserAction::Propose { spec } => vec!["propose".into(), spec],
        UserAction::Reproduce { record } => vec!["reproduce".into(), record],
        UserAction::Fetch { record } => vec!["fetch".into(), record],
        UserAction::Select { checkpoint } => vec!["select".into(), checkpoint],
        UserAction::Export {
            checkpoint,
            directory,
        } => vec!["export".into(), checkpoint, directory],
    };
    if args.iter().any(|a| a.len() > 8192 || a.contains('\0')) {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let home = app.home.clone();
    let result = tokio::task::spawn_blocking(move || -> anyhow::Result<serde_json::Value> {
        let _permit = permit;
        let result = std::process::Command::new(std::env::current_exe()?)
            .arg("--home")
            .arg(home)
            .args(args)
            .output()?;
        anyhow::ensure!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        Ok(serde_json::from_slice(&result.stdout)?)
    })
    .await;
    match result {
        Ok(Ok(value)) => Json(value).into_response(),
        Ok(Err(error)) => (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({"error":error.to_string()})),
        )
            .into_response(),
        Err(_) => StatusCode::INTERNAL_SERVER_ERROR.into_response(),
    }
}
pub fn serve(home: PathBuf, store: ArtifactStore, token_file: &FsPath, port: u16) -> Result<()> {
    let app = Arc::new(App {
        home,
        store,
        token: nc_dkg_client::read_token(token_file)?,
        permits: Arc::new(tokio::sync::Semaphore::new(2)),
        commands: Arc::new(tokio::sync::Semaphore::new(1)),
    });
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    runtime.block_on(async {
        let router=Router::new().route("/",get(||async {Html(include_str!("../../../web/index.html"))}))
            .route("/app.js",get(||async {([(header::CONTENT_TYPE,"text/javascript")],include_str!("../../../web/app.js"))}))
            .route("/api/state",get(state)).route("/api/actions",post(action)).route("/api/artifact-metadata/{id}",get(artifact)).with_state(app)
            .layer(axum::middleware::from_fn(|req:axum::extract::Request,next:axum::middleware::Next|async move {
                let mut r=next.run(req).await;
                r.headers_mut().insert(header::CONTENT_SECURITY_POLICY,"default-src 'self'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'".parse().unwrap());
                r.headers_mut().insert(header::CACHE_CONTROL,"no-store".parse().unwrap());r
            }));
        let listener=tokio::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST,port)).await?;
        eprintln!("Neural Commons http://127.0.0.1:{port}");
        axum::serve(listener,router).with_graceful_shutdown(async{let _=tokio::signal::ctrl_c().await;}).await?;Ok(())
    })
}
