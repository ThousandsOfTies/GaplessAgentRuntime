# Gapless Agent Runtime WSL hub commands.

UID ?= 04:AB:CD:EF:01:23
SCENARIO ?= scenarios/sensor_demo_rfid.json
VSCODE_EXT_NAME = gar-terminal-bridge
VSCODE_EXT_VERSION = 0.0.1
VSCODE_EXT_SRC = tools/vscode-gar
VSCODE_EXT_DEST ?= $(HOME)/.vscode-server/extensions/$(VSCODE_EXT_NAME)-$(VSCODE_EXT_VERSION)
MCP_SERVER = $(CURDIR)/tools/gar-mcp/server.py
GAR_REQUIREMENTS = requirements-gar.txt

SSH_DST = $(if $(KEY),ubuntu@$(EC2),$(EC2))
SSH     = ssh $(if $(KEY),-i $(KEY),)
SCP     = scp $(if $(KEY),-i $(KEY),)

.PHONY: gar init start port-forward port-forward-stop port-forward-status sim-test sim-scenario

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
	.venv/bin/python -m pip install -r $(GAR_REQUIREMENTS)
	ln -sf $(CURDIR)/scripts/gar .venv/bin/gar
	mkdir -p $(dir $(VSCODE_EXT_DEST))
	rm -rf $(VSCODE_EXT_DEST)
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
	tools/forward_ec2_ports.sh --host $(or $(EC2),vibecode-graviton)

port-forward-stop:
	tools/forward_ec2_ports.sh --host $(or $(EC2),vibecode-graviton) --stop

port-forward-status:
	tools/forward_ec2_ports.sh --host $(or $(EC2),vibecode-graviton) --status

sim-test:
ifndef EC2
	$(error EC2 変数を指定してください: make sim-test EC2=vibecode-graviton)
endif
	scripts/gar sim ui button press 17 --duration-ms 150 --host $(EC2)
	@sleep 1
	scripts/gar sim ui rfid tap $(UID) --host $(EC2)
	@sleep 1
	scripts/gar sim env status --host $(EC2)
	scripts/gar sim env log --host $(EC2)

sim-scenario:
ifndef EC2
	$(error EC2 変数を指定してください: make sim-scenario EC2=vibecode-graviton SCENARIO=scenarios/sensor_demo_rfid.json)
endif
	$(SSH) $(SSH_DST) 'mkdir -p ~/gar-scenarios'
	$(SCP) scripts/run_scenario.py $(SCENARIO) $(SSH_DST):~/gar-scenarios/
	$(SSH) $(SSH_DST) 'python3 ~/gar-scenarios/run_scenario.py ~/gar-scenarios/$(notdir $(SCENARIO)) --base-url http://127.0.0.1:8080'
