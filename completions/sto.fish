# fish completion for sto
# install: cp to ~/.config/fish/completions/sto.fish

set -l cmds list close merge move sort dedupe group-by-folder dump-untitled find save-all reload save restore sessions recent pick ping

complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a list           -d "list all windows and tabs"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a close          -d "close tabs by id, glob, or saved"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a merge          -d "merge all windows into one"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a move           -d "move a single tab to another window"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a sort           -d "sort tabs in active group"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a dedupe         -d "close duplicate file tabs"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a group-by-folder -d "split tabs by project folder"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a dump-untitled  -d "save untitled tabs"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a find           -d "grep across open buffers"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a save-all       -d "save all dirty tabs"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a reload         -d "reload tabs from disk"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a save           -d "save session"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a restore        -d "restore session"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a sessions       -d "manage sessions"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a recent         -d "recently closed tabs"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a pick           -d "interactive picker"
complete -c sto -n "not __fish_seen_subcommand_from $cmds" -a ping           -d "health check"

complete -c sto -n "__fish_seen_subcommand_from close"         -l pattern -l saved -l dry-run
complete -c sto -n "__fish_seen_subcommand_from merge"         -l into -l copy-unsaved -l dry-run
complete -c sto -n "__fish_seen_subcommand_from move"          -l to -l dry-run
complete -c sto -n "__fish_seen_subcommand_from sort"          -l by -xa 'name path ext'
complete -c sto -n "__fish_seen_subcommand_from dedupe"        -l dry-run
complete -c sto -n "__fish_seen_subcommand_from dump-untitled" -l dir -l close-source -l open-saved -l include-dirty -l dry-run
complete -c sto -n "__fish_seen_subcommand_from find"          -l regex -l case-sensitive
complete -c sto -n "__fish_seen_subcommand_from save-all"      -l dry-run
complete -c sto -n "__fish_seen_subcommand_from reload"        -l pattern -l dry-run
complete -c sto -n "__fish_seen_subcommand_from restore"       -l close-existing
complete -c sto -n "__fish_seen_subcommand_from sessions"      -xa 'list delete'
complete -c sto -n "__fish_seen_subcommand_from recent"        -l limit -l restore -l clear
complete -c sto -n "__fish_seen_subcommand_from pick"          -xa 'close print'
complete -c sto -n "__fish_seen_subcommand_from list"          -l json

function __sto_sessions
    set -l dir (set -q STO_SESSIONS_DIR; and echo $STO_SESSIONS_DIR; or echo ~/.sto/sessions)
    if test -d $dir
        for f in $dir/*.json
            basename $f .json
        end
    end
end
complete -c sto -n "__fish_seen_subcommand_from save restore" -xa "(__sto_sessions)"
