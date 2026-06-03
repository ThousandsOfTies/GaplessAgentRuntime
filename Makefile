# AgentCockpit WSL hub commands.

UID ?= 04:AB:CD:EF:01:23
SCENARIO ?= scenarios/sensor_demo_rfid.json
VSCODE_EXT_NAME = agentcockpit-terminal-bridge
VSCODE_EXT_VERSION = 0.0.1
VSCODE_EXT_SRC = tools/vscode-agentcockpit
VSCODE_EXT_DEST ?= $(HOME)/.vscode-server/extensions/$(VSCODE_EXT_NAME)-$(VSCODE_EXT_VERSION)
MCP_SERVER = $(CURDIR)/tools/agentcockpit-mcp/server.py

SSH_DST = $(if $(KEY),ubuntu@$(EC2),$(EC2))
SSH     = ssh $(if $(KEY),-i $(KEY),)
SCP     = scp $(if $(KEY),-i $(KEY),)

.PHONY: agp init start port-forward port-forward-stop port-forward-status sim-test sim-scenario

agp:
	$(error make agp は廃止しました。初期構築は make init、日常開始は make start を使ってください)

init:
	python3 -m venv --without-pip .venv
	ln -sf $(CURDIR)/scripts/agp .venv/bin/agp
	mkdir -p $(dir $(VSCODE_EXT_DEST))
	rm -rf $(VSCODE_EXT_DEST)
	cp -R $(VSCODE_EXT_SRC) $(VSCODE_EXT_DEST)
	@echo "Installed AgentCockpit VSCode extension to $(VSCODE_EXT_DEST)"
	mkdir -p .agp
	@{ \
	  printf '{\n'; \
	  printf '  "mcpServers": {\n'; \
	  printf '    "agentcockpit": {\n'; \
	  printf '      "command": "python3",\n'; \
	  printf '      "args": ["%s"]\n' "$(MCP_SERVER)"; \
	  printf '    }\n'; \
	  printf '  }\n'; \
	  printf '}\n'; \
	} > .agp/mcp-config.json
	@echo "Wrote MCP config to .agp/mcp-config.json"
	@echo "Run: make start"
	@echo "Reload VSCode window to activate the terminal bridge extension."

start:
	@test -x .venv/bin/agp || { echo "Run 'make init' first."; exit 1; }
	@echo "Entering AgentCockpit virtual environment... (Type 'exit' to leave)"
	@bash -c 'TMP_RC=$$(mktemp); echo "source ~/.bashrc" > $$TMP_RC; echo "source $(CURDIR)/.venv/bin/activate" >> $$TMP_RC; echo "rm -f $$TMP_RC" >> $$TMP_RC; exec bash --rcfile $$TMP_RC -i'

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
	scripts/agp sim button press 17 --duration-ms 150 --host $(EC2)
	@sleep 1
	scripts/agp sim rfid tap $(UID) --host $(EC2)
	@sleep 1
	scripts/agp sim status --host $(EC2)
	scripts/agp sim log --host $(EC2)

sim-scenario:
ifndef EC2
	$(error EC2 変数を指定してください: make sim-scenario EC2=vibecode-graviton SCENARIO=scenarios/sensor_demo_rfid.json)
endif
	$(SSH) $(SSH_DST) 'mkdir -p ~/agentcockpit-scenarios'
	$(SCP) scripts/run_scenario.py $(SCENARIO) $(SSH_DST):~/agentcockpit-scenarios/
	$(SSH) $(SSH_DST) 'python3 ~/agentcockpit-scenarios/run_scenario.py ~/agentcockpit-scenarios/$(notdir $(SCENARIO)) --base-url http://127.0.0.1:8080'
