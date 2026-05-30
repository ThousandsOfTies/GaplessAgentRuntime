const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

const REQUEST_GLOB = "**/.agp/terminal-requests/*.json";
const terminals = new Map();
const processedRequests = new Set();

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("agentcockpit.runAgpSetup", () => {
      const folder = workspaceFolder();
      if (!folder) {
        vscode.window.showErrorMessage("AgentCockpit workspace folder was not found.");
        return;
      }

      runInTerminal({
        title: "AgentCockpit",
        cwd: folder.fsPath,
        command: ".venv/bin/agp setup",
      });
    })
  );

  const watcher = vscode.workspace.createFileSystemWatcher(REQUEST_GLOB);
  context.subscriptions.push(watcher);

  watcher.onDidCreate((uri) => processRequest(uri));
  watcher.onDidChange((uri) => processRequest(uri));

  vscode.workspace.findFiles(REQUEST_GLOB).then((uris) => {
    for (const uri of uris) {
      processRequest(uri);
    }
  });
}

function deactivate() {}

function processRequest(uri) {
  let request;
  try {
    request = JSON.parse(fs.readFileSync(uri.fsPath, "utf8"));
  } catch {
    return;
  }

  const id = String(request.id || path.basename(uri.fsPath, ".json"));
  if (processedRequests.has(id)) {
    return;
  }
  processedRequests.add(id);

  if (typeof request.command !== "string" || request.command.trim() === "") {
    vscode.window.showWarningMessage(`AgentCockpit terminal request ${id} has no command.`);
    writeStatus(uri, request, "invalid", "Terminal request has no command.");
    markRequest(uri, "invalid");
    return;
  }

  const terminal = runInTerminal({
    title: request.title || "AgentCockpit",
    cwd: request.cwd || workspaceFolder()?.fsPath,
    command: request.command,
  });
  writeStatus(uri, request, "started", `Sent to VSCode terminal: ${terminal.name}`);
  markRequest(uri, "started");
}

function runInTerminal(request) {
  const title = request.title || "AgentCockpit";
  let terminal = terminals.get(title);
  if (!terminal || terminal.exitStatus) {
    terminal = vscode.window.createTerminal({ name: title, cwd: request.cwd });
    terminals.set(title, terminal);
  }

  terminal.show(false);
  if (request.cwd) {
    terminal.sendText(`cd ${shellQuote(request.cwd)}`);
  }
  terminal.sendText(request.command);
  return terminal;
}

function markRequest(uri, status) {
  const processedDir = path.join(path.dirname(uri.fsPath), "processed");
  fs.mkdirSync(processedDir, { recursive: true });

  const target = path.join(
    processedDir,
    `${path.basename(uri.fsPath, ".json")}.${status}.json`
  );

  try {
    fs.renameSync(uri.fsPath, target);
  } catch {
    // The request may have been moved by another extension host event.
  }
}

function writeStatus(uri, request, status, message) {
  const statusDir = path.join(agpRootFromRequestUri(uri), "terminal-status");
  fs.mkdirSync(statusDir, { recursive: true });

  const id = String(request.id || path.basename(uri.fsPath, ".json"));
  const statusPath = path.join(statusDir, `${id}.json`);
  const payload = {
    id,
    status,
    message,
    title: request.title || "AgentCockpit",
    command: request.command || "",
    cwd: request.cwd || workspaceFolder()?.fsPath || "",
    updated_at: new Date().toISOString(),
  };
  fs.writeFileSync(statusPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function agpRootFromRequestUri(uri) {
  return path.dirname(path.dirname(uri.fsPath));
}

function workspaceFolder() {
  return vscode.workspace.workspaceFolders?.[0]?.uri;
}

function shellQuote(value) {
  return `'${String(value).replace(/'/g, "'\\''")}'`;
}

module.exports = {
  activate,
  deactivate,
};
