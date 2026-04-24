# bash completion for sto
# install: source this file from your ~/.bashrc, or drop it into a bash-completion dir.

_sto() {
    local cur prev words
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    local commands="list close merge move sort dedupe group-by-folder dump-untitled find save-all reload save restore sessions recent pick ping"

    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
        return 0
    fi

    local sub="${COMP_WORDS[1]}"
    case "$sub" in
        list)           COMPREPLY=( $(compgen -W "--json" -- "$cur") ) ;;
        close)          COMPREPLY=( $(compgen -W "--pattern --saved --dry-run" -- "$cur") ) ;;
        merge)          COMPREPLY=( $(compgen -W "--into --copy-unsaved --dry-run" -- "$cur") ) ;;
        move)           COMPREPLY=( $(compgen -W "--to --dry-run" -- "$cur") ) ;;
        sort)           [ "$prev" = "--by" ] && COMPREPLY=( $(compgen -W "name path ext" -- "$cur") ) \
                                              || COMPREPLY=( $(compgen -W "--by" -- "$cur") ) ;;
        dedupe)         COMPREPLY=( $(compgen -W "--dry-run" -- "$cur") ) ;;
        dump-untitled)  COMPREPLY=( $(compgen -W "--dir --close-source --open-saved --include-dirty --dry-run" -- "$cur") ) ;;
        find)           COMPREPLY=( $(compgen -W "--regex --case-sensitive" -- "$cur") ) ;;
        save-all)       COMPREPLY=( $(compgen -W "--dry-run" -- "$cur") ) ;;
        reload)         COMPREPLY=( $(compgen -W "--pattern --dry-run" -- "$cur") ) ;;
        save|restore)
            local dir="${STO_SESSIONS_DIR:-$HOME/.sto/sessions}"
            if [ -d "$dir" ]; then
                local names
                names=$(cd "$dir" && ls *.json 2>/dev/null | sed 's/\.json$//')
                COMPREPLY=( $(compgen -W "$names --close-existing" -- "$cur") )
            fi
            ;;
        sessions)       COMPREPLY=( $(compgen -W "list delete" -- "$cur") ) ;;
        recent)         COMPREPLY=( $(compgen -W "--limit --restore --clear" -- "$cur") ) ;;
        pick)           COMPREPLY=( $(compgen -W "close print" -- "$cur") ) ;;
    esac
}
complete -F _sto sto
