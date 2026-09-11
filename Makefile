# Gapless Agent Runtime bootstrap and developer checks.
# 日常のproduct操作は make targetではなく `gar` CLIを使用します。

.DEFAULT_GOAL := help

UID ?= 04:AB:CD:EF:01:23
APP_REPO ?= ../../GarAdhocApp/sources/gar-adhoc-app
SCENARIO ?= $(APP_REPO)/scenarios/sensor_demo_rfid.json
VSCODE_EXT_NAME = gar-terminal-bridge
VSCODE_EXT_VERSION = 0.0.3
VSCODE_EXT_SRC = tools/vscode-gar
VSCODE_EXT_DEST ?= $(HOME)/.vscode-server/extensions/$(VSCODE_EXT_NAME)-$(VSCODE_EXT_VERSION)
MCP_SERVER = $(CURDIR)/tools/gar-mcp/server.py
GAR_DEV_REQUIREMENTS = requirements-dev.txt
PYTHON = .venv/bin/python
RUFF = .venv/bin/ruff

SIM_HOST ?= $(EC2)
SSH_DST = $(if $(KEY),ubuntu@$(SIM_HOST),$(SIM_HOST))
SSH     = ssh $(if $(KEY),-i $(KEY),)
SCP     = scp $(if $(KEY),-i $(KEY),)

.PHONY: help check gar init start port-forward port-forward-stop port-forward-status sim-test sim-scenario

help:
	@echo "Gapless Agent Runtime development commands"
	@echo "  make init          Create the venv and install local VS Code/MCP integration"
	@echo "  make start         Enter an interactive shell with gar completion"
	@echo "  make check         Run lint, tests, and syntax checks"
	@echo "  make port-forward  Start the selected Simulation Host panel port forward"

check:
	@test -x $(PYTHON) || { echo "Run 'make init' first."; exit 1; }
	@test -x $(RUFF) || { echo "Ruff is missing from .venv; run 'make init' first."; exit 1; }
	$(RUFF) check scripts scripts/gar_lib/build tests tools/*.py tools/gar-mcp/server.py
	$(RUFF) format --check scripts scripts/gar_lib/build tests tools/*.py tools/gar-mcp/server.py
	$(PYTHON) -m unittest discover -s tests -v
	bash -n tools/forward_sim_ports.sh tools/forward_ec2_ports.sh tools/setup_codespace_wsl.sh scripts/create-product-devspace.sh
	node --check tools/vscode-gar/extension.js
	node --test tools/vscode-gar/*.test.js

gar:
	$(error make gar は廃止しました。初期構築は make init、日常開始は make start を使ってください)

init:
	@if [ ! -x .venv/bin/python ]; then \
	  python3 -m venv .venv || { \
	    echo "python3 -m venv が pip 付き venv を作成できませんでした。"; \
	    echo "WSL/Ubuntu では sudo apt-get install python3-venv を実行してから make init を再実行してください。"; \
	    exit 1; \
	  }; \
	fi
	@.venv/bin/python -m pip --version >/dev/null 2>&1 || { \
	  echo ".venv に pip がありません。rm -rf .venv 後、python3-venv を導入して make init を再実行してください。"; \
	  echo "例: sudo apt-get install python3-venv && rm -rf .venv && make init"; \
	  exit 1; \
	}
	.venv/bin/python -m pip install -r $(GAR_DEV_REQUIREMENTS)
	chmod +x scripts/gar
	ln -sf $(CURDIR)/scripts/gar .venv/bin/gar
	mkdir -p $(dir $(VSCODE_EXT_DEST))
	rm -rf $(HOME)/.vscode-server/extensions/$(VSCODE_EXT_NAME)-*
	cp -R $(VSCODE_EXT_SRC) $(VSCODE_EXT_DEST)
	@echo "Installed Gapless Agent Runtime VSCode extension to $(VSCODE_EXT_DEST)"
	mkdir -p .gar
	@{ \
	  printf '{\n'; \
	  printf '  "mcpServers": {\n'; \
	  printf '    "gar": {\n'; \
	  printf '      "command": "python3",\n'; \
	  printf '      "args": ["%s"]\n' "$(MCP_SERVER)"; \
	  printf '    }\n'; \
	  printf '  }\n'; \
	  printf '}\n'; \
	} > .gar/mcp-config.json
	@echo "Wrote MCP config to .gar/mcp-config.json"
	@echo "Run: make start"
	@echo "Reload VSCode window to activate the terminal bridge extension."

start:
	@test -x .venv/bin/gar || { echo "Run 'make init' first."; exit 1; }
	@echo "Entering Gapless Agent Runtime virtual environment... (Type 'exit' to leave)"
	@bash -c 'TMP_RC=$$(mktemp); echo "source ~/.bashrc" > $$TMP_RC; echo "source $(CURDIR)/.venv/bin/activate" >> $$TMP_RC; echo "source <($(CURDIR)/.venv/bin/gar completion bash)" >> $$TMP_RC; echo "rm -f $$TMP_RC" >> $$TMP_RC; exec bash --rcfile $$TMP_RC -i'

port-forward:
ifndef SIM_HOST
	$(error SIM_HOST 変数を指定してください: make port-forward SIM_HOST=your-ssh-host)
endif
	tools/forward_sim_ports.sh --host $(SIM_HOST)

port-forward-stop:
ifndef SIM_HOST
	$(error SIM_HOST 変数を指定してください: make port-forward-stop SIM_HOST=your-ssh-host)
endif
	tools/forward_sim_ports.sh --host $(SIM_HOST) --stop

port-forward-status:
ifndef SIM_HOST
	$(error SIM_HOST 変数を指定してください: make port-forward-status SIM_HOST=your-ssh-host)
endif
	tools/forward_sim_ports.sh --host $(SIM_HOST) --status

sim-test:
ifndef WORKSPACE
	$(error WORKSPACE 変数を指定してください: make sim-test WORKSPACE=Local/Product)
endif
	scripts/gar sim io press --device button --line 17 --duration-ms 150 --workspace $(WORKSPACE)
	@sleep 1
	scripts/gar sim io set --device rfid --uid $(UID) --workspace $(WORKSPACE)
	@sleep 1
	scripts/gar sim status --workspace $(WORKSPACE)
	scripts/gar sim log --workspace $(WORKSPACE)

sim-scenario:
ifndef SIM_HOST
	$(error SIM_HOST 変数を指定してください: make sim-scenario SIM_HOST=your-ssh-host SCENARIO=$(APP_REPO)/scenarios/sensor_demo_rfid.json)
endif
	$(SSH) $(SSH_DST) 'mkdir -p ~/gar-scenarios'
	$(SCP) scripts/run_scenario.py scripts/gar_lib/simulation/hardware/io_actions.py $(SCENARIO) $(SSH_DST):~/gar-scenarios/
	$(SSH) $(SSH_DST) 'python3 ~/gar-scenarios/run_scenario.py ~/gar-scenarios/$(notdir $(SCENARIO)) --base-url http://127.0.0.1:8080'
