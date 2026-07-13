#!/usr/bin/env bash
# Create an application-specific gar-build-env product branch and workspace.
#
# This is deliberately a standalone bootstrap script, rather than a `gar`
# subcommand: it creates the product workspace that `gar setup` configures.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  create-product-devspace.sh PRODUCT_NAME APP_REPOSITORY [options]

Create a sibling checkout of gar-build-env, a product branch, and the initial
application + gar-tools submodules. PRODUCT_NAME is used for both the branch
and, by default, the checkout directory.

Options:
  --destination DIR       Checkout path (default: PRODUCT_NAME in the current directory)
  --app-path PATH         App submodule path (default: sources/<repo-name>)
  --build-env-repo URL    gar-build-env repository URL
  --gar-tools-repo URL    gar-tools repository URL
  --push                  Push the new product branch after its initial commit
  --dry-run               Print the git commands without changing anything
  -h, --help              Show this help

Example:
  scripts/create-product-devspace.sh GarStreamTx \
    https://github.com/ThousandsOfTies/gar-stream-tx \
    --destination /home/user/Yurufuwa/GarStreamTx

After the script succeeds, implement the application-specific commands in
scripts/product-sim-build.sh and scripts/product-target-build.sh, then run
`gar setup` and add the checkout from
the interactive Product Workspaces screen.
EOF
}

die() {
  echo "create-product-devspace: $*" >&2
  exit 1
}

run() {
  if [[ "${dry_run}" == 1 ]]; then
    printf '+ '
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

product_name=""
app_repository=""
destination=""
app_path=""
build_env_repository="https://github.com/ThousandsOfTies/gar-build-env"
gar_tools_repository="https://github.com/ThousandsOfTies/gar-tools"
push_branch=0
dry_run=0

positionals=()
while (($#)); do
  case "$1" in
    --destination)
      (($# >= 2)) || die "--destination requires a value"
      destination="$2"
      shift 2
      ;;
    --app-path)
      (($# >= 2)) || die "--app-path requires a value"
      app_path="$2"
      shift 2
      ;;
    --build-env-repo)
      (($# >= 2)) || die "--build-env-repo requires a value"
      build_env_repository="$2"
      shift 2
      ;;
    --gar-tools-repo)
      (($# >= 2)) || die "--gar-tools-repo requires a value"
      gar_tools_repository="$2"
      shift 2
      ;;
    --push)
      push_branch=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --*)
      die "unknown option: $1"
      ;;
    *)
      positionals+=("$1")
      shift
      ;;
  esac
done

((${#positionals[@]} == 2)) || {
  usage >&2
  exit 2
}
product_name="${positionals[0]}"
app_repository="${positionals[1]}"

[[ "${product_name}" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ ]] || die "invalid product name: ${product_name}"

repo_name="${app_repository%/}"
repo_name="${repo_name##*/}"
repo_name="${repo_name%.git}"
[[ -n "${repo_name}" ]] || die "cannot derive an app name from: ${app_repository}"

destination="${destination:-${product_name}}"
app_path="${app_path:-sources/${repo_name}}"
[[ "${app_path}" != /* && "${app_path}" != *".."* ]] || die "app path must be a relative path below the workspace"

if [[ -e "${destination}" ]]; then
  die "destination already exists: ${destination}"
fi

if [[ "${dry_run}" == 1 ]]; then
  printf 'Would create product workspace:\n'
  printf '  branch:      %s\n' "${product_name}"
  printf '  destination: %s\n' "${destination}"
  printf '  app:         %s -> %s\n' "${app_repository}" "${app_path}"
  printf '  tools:       %s -> sources/gar-tools\n' "${gar_tools_repository}"
fi

run git clone --no-recurse-submodules "${build_env_repository}" "${destination}"
run git -C "${destination}" checkout -b "${product_name}" origin/main
run git -C "${destination}" submodule add -b main "${app_repository}" "${app_path}"
run git -C "${destination}" submodule add -b main "${gar_tools_repository}" sources/gar-tools

if [[ "${dry_run}" == 0 ]]; then
  cp "${destination}/config/product.env.example" "${destination}/config/product.env"
  cp "${destination}/scripts/product-sim-build.sh.example" "${destination}/scripts/product-sim-build.sh"
  cp "${destination}/scripts/product-target-build.sh.example" "${destination}/scripts/product-target-build.sh"
  chmod +x "${destination}/scripts/product-sim-build.sh"
  chmod +x "${destination}/scripts/product-target-build.sh"
  {
    printf '\n# Product workspace paths created by create-product-devspace.sh.\n'
    printf 'export GAR_PRODUCT_NAME=%q\n' "${product_name}"
    printf 'export GAR_SIM_APP_DIR=%q\n' "${app_path}"
    printf 'export GAR_TOOLS_DIR=%q\n' "sources/gar-tools"
  } >> "${destination}/config/product.env"
fi

run git -C "${destination}" add .gitmodules config/product.env scripts/product-sim-build.sh scripts/product-target-build.sh "${app_path}" sources/gar-tools
run git -C "${destination}" commit -m "Initialize ${product_name} product devspace"

if [[ "${push_branch}" == 1 ]]; then
  run git -C "${destination}" push -u origin "${product_name}"
fi

if [[ "${dry_run}" == 1 ]]; then
  printf '\nDry run complete; no workspace was created.\n'
  exit 0
fi

printf '\nCreated %s at %s.\n' "${product_name}" "${destination}"
printf 'Next: edit %s/scripts/product-sim-build.sh and product-target-build.sh, then run:\n' "${destination}"
printf '  gar setup\n'
printf '  # Product Workspaces で追加し、local path に %q を入力\n' "${destination}"
