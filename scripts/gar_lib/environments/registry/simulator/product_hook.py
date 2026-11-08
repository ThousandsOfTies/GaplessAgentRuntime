from scripts.gar_lib.environments.setup_option import SimulationEnvironmentSetupOption


class ProductHookEnvironment(SimulationEnvironmentSetupOption):
    environment_id = "product_hook"
    display_name = "Product-managed simulator lifecycle"
    description = "Use the Product Python lifecycle adapter with GAR checksum snapshots"
    display_order = 35
    required_commands = ()
