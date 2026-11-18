#!/usr/bin/env bash

#call global env
#jupyter-lab \
#	--no-browser
#	--notebook-dir

# jupyter-lab args: (leave empty if you don't want to change them)

### path to python jupyter config
#default config is global one at: '/home/tony/.jupyter/jupyter_lab_config.py'
#__JUPYTER_CONFIG="conf.py" 


##other interesting ones: --custom-css
# --ip
# --port
# password seems to be more complex now...use custom config if needed


#!/usr/bin/env bash

#======================================================================(70)
# settings
#----------------------------------------------------------------------(70)
__JUPYTER_ROOT="jupyter"   		#name of jupyter dir (within the project folder)
__JUPYTER_CONFIG="jupyter/.jupyter-conf.py"      #path to conf, relative to project root


#! the relative path of the project root (wrt script root)
#if the project root is up one dir, use: "/../"
#if the project root is the same as the root dir: ""
__PATH_TO_PROJECT="../"


#======================================================================(70)
# functions
#----------------------------------------------------------------------(70)
#do this once at the top-most level to avoid issues with ${BASE_SOURCE[]}
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

# __JUPYTER_CMD_PREFIX_LOCAL="pixi run jupyter lab"
# __JUPYTER_CMD_PREFIX_GLOBAL="jupyter-lab"
# __JUPYTER_CMD_PREFIX=$__JUPYTER_CMD_PREFIX_LOCAL


__JUPYTER_CMD_PREFIX_LOCAL=(pixi run jupyter lab)
__JUPYTER_CMD_PREFIX_GLOBAL=(jupyter-lab)
__JUPYTER_CMD_PREFIX=("${__JUPYTER_CMD_PREFIX_LOCAL[@]}")

CMD=("${__JUPYTER_CMD_PREFIX[@]}" "--no-browser")



#general utils
function resolve() {
	#combines an arbitrary number of args into a path using python
	#r1="$(resolve "${SCRIPT_DIR}" "maor" "winne" "bago")"
	#echo "Testing resolve: ${r1}"

	#orig:
	#python3 -c 'import os, sys; print(os.path.normpath(os.path.join(*sys.argv[1:])))' "$@"

	#strip leading slashes from all but first, one-line version:
	#function resolve() {
    #python3 -c 'import os, sys; args = sys.argv[1:]; print(os.path.normpath(os.path.join(args[0], *[a.lstrip("/") for a in args[1:]]))) if args else None' "$@"
    #}

    #strip leading slashes from all but first
    python3 -c '
		import os, sys

		args = sys.argv[1:]
		if not args:
		    sys.exit(0)

		# Keep first argument intact; strip leading slashes from all subsequent relative arguments
		base = args[0]
		rest = [arg.lstrip("/") for arg in args[1:]]

		print(os.path.normpath(os.path.join(base, *rest)))
	' "$@"
}
function pause() {
	#! pauses until a key is pressed
	#! $1: the message to display (has a default) 

    read -n 1 -s -r -p "${1:-Press any key to continue, or ctrl+c to quit...}"
    echo ""
}

#path functions
function get_script_dir() {
	#! gets the directory of the current script
	#https://www.baeldung.com/linux/bash-get-location-within-script
    #local source_file="${BASH_SOURCE[1]}" # Note: index 1 when inside a nested function call
    #local script_dir

    #script_dir="$(cd -- "$(dirname -- "$source_file")" &> /dev/null && pwd)"
    #echo "$script_dir"
    echo $SCRIPT_DIR
}
function get_project_root() {
	#! returns the project root dir from the script's dir

	#local script_dir=$(get_script_dir)
	#local root_loc=${__root_loc_wrt_script}

	resolve "$(get_script_dir)" "${__PATH_TO_PROJECT}"
}
function get_jupyter_root() {
	#! returns jupyter root dir
	resolve "$(get_project_root)" "${__JUPYTER_ROOT}"
}

# exec builder - returns an array via stdout or global array
function build_jupyter_cmd() {
	#! $1: (optional) jupyter root dir

    local root="${1:-}"

    # Build as an array to handle spaces and flags perfectly
    #CMD=("${__JUPYTER_CMD_PREFIX}" "--no-browser" "--custom-css")
    CMD=("${__JUPYTER_CMD_PREFIX[@]}" "--no-browser" "--custom-css")


    #handle: notebook dir
    if [[ -n "$root" ]]; then
        CMD+=("--notebook-dir=${root}")

        # Check if the directory actually exists on disk
        if [[ ! -d "$root" ]]; then
            echo "[ERROR] Jupyter root directory does not exist: '$root'" >&2
            exit 1
        fi
    fi

    #handle: custom python config
    if [[ -n "${__JUPYTER_CONFIG:-}" ]]; then
        local config
        config="$(resolve "$(get_project_root)" "${__JUPYTER_CONFIG}")"

        # Check if the config file exists
        if [[ ! -f "$config" ]]; then
            echo "[ERROR] Jupyter config file does not exist: '$config'" >&2
            exit 1
        fi

        CMD+=("--config=${config}")
    fi
}



#======================================================================(70)
# output/main
#----------------------------------------------------------------------(70)
clear

echo "#=================================================="
echo "# JUPYTER LAB LAUNCHER..."
echo "#--------------------------------------------------"
echo "# - Access it via: http://localhost:8888"
echo "# - Password (is probably): tonytony"
echo "#--------------------------------------------------"
echo "# Environment:"
echo "# - script/launcher dir: $(get_script_dir)"
echo "# - project root:        $(get_project_root)"
echo "# - jupyter root:        $(get_jupyter_root)"
echo "#--------------------------------------------------"
echo ""
echo ""


# Build array command
build_jupyter_cmd "$(get_jupyter_root)"

echo "Jupyter command:"
echo "${CMD[*]}"
echo ""

pause

echo "Running..."

# Execute array safely preserving spaces and arguments
"${CMD[@]}"
