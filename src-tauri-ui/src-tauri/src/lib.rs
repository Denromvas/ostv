// OsTv UI — Tauri backend (Rust)

use serde_json::Value;
use std::path::Path;
use tauri::Manager;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixStream;

const BRAIN_SOCKET: &str = "/run/ostv/brain.sock";

#[tauri::command]
async fn brain_call(method: String, params: Value) -> Result<Value, String> {
    if !Path::new(BRAIN_SOCKET).exists() {
        return Err(format!("brain socket missing: {}", BRAIN_SOCKET));
    }
    let mut stream = UnixStream::connect(BRAIN_SOCKET)
        .await
        .map_err(|e| format!("connect: {}", e))?;

    let req = serde_json::json!({
        "method": method,
        "params": params,
        "id": 1,
    });
    let line = format!("{}\n", req);
    stream
        .write_all(line.as_bytes())
        .await
        .map_err(|e| format!("write: {}", e))?;
    stream.flush().await.ok();

    let (read_half, _w) = stream.split();
    let mut reader = BufReader::new(read_half);
    let mut resp_line = String::new();
    let n = reader
        .read_line(&mut resp_line)
        .await
        .map_err(|e| format!("read: {}", e))?;
    if n == 0 {
        return Err("empty response".into());
    }
    let resp: Value = serde_json::from_str(&resp_line)
        .map_err(|e| format!("parse: {} (raw: {})", e, resp_line))?;
    Ok(resp)
}

#[tauri::command]
async fn exit_app(app: tauri::AppHandle) {
    app.exit(0);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            // Ensure fullscreen (config may be ignored by some WMs)
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_fullscreen(true);
                let _ = window.set_focus();
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![brain_call, exit_app])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
