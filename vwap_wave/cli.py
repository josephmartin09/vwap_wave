import cmd
import shlex

from .catalog import INDICATOR_COLUMNS, SYMBOLS
from .commands import (
    ReplaceAlertConditions,
    ShowAlertConditions,
    UnixCommandClient,
)


class VwapWaveCli(cmd.Cmd):
    intro = "Type 'help' for commands. Indicator names match dataframe columns."
    prompt = "vwap> "

    def __init__(self, command_client, symbols, indicator_names, **kwargs):
        super().__init__(**kwargs)
        self.command_client = command_client
        self.symbols = tuple(symbols)
        self.indicator_names = tuple(indicator_names)

    def cmdloop(self, intro=None):
        """Run the shell, treating terminal EOF as input rather than a command."""
        self.preloop()
        if self.use_rawinput and self.completekey:
            try:
                import readline

                self.old_completer = readline.get_completer()
                readline.set_completer(self.complete)
                readline.parse_and_bind(self.completekey + ": complete")
            except ImportError:
                pass

        try:
            if intro is not None:
                self.intro = intro
            if self.intro:
                self.stdout.write(str(self.intro) + "\n")

            stop = None
            while not stop:
                if self.cmdqueue:
                    line = self.cmdqueue.pop(0)
                elif self.use_rawinput:
                    try:
                        line = input(self.prompt)
                    except EOFError:
                        self.stdout.write("\n")
                        break
                else:
                    self.stdout.write(self.prompt)
                    self.stdout.flush()
                    line = self.stdin.readline()
                    if not line:
                        break
                    line = line.rstrip("\r\n")

                line = self.precmd(line)
                stop = self.onecmd(line)
                stop = self.postcmd(stop, line)
            self.postloop()
        finally:
            if self.use_rawinput and self.completekey:
                try:
                    import readline

                    readline.set_completer(self.old_completer)
                except ImportError:
                    pass

    def do_set(self, argument):
        """set SYMBOL [INDICATOR ...]

        Replace all alert conditions for SYMBOL. Supplying no indicators sends
        an empty replacement, which means snooze.
        """
        try:
            parts = shlex.split(argument)
        except ValueError as error:
            self._reject(str(error))
            return

        if not parts:
            self._reject("usage: set SYMBOL [INDICATOR ...]")
            return

        symbol = self._resolve_symbol(parts[0])
        if symbol is None:
            self._reject("unknown symbol: " + parts[0])
            return

        conditions = tuple(parts[1:])
        unknown = [
            condition
            for condition in conditions
            if condition not in self.indicator_names
        ]
        if unknown:
            self._reject("unknown indicator: " + unknown[0])
            return

        self._send(ReplaceAlertConditions(symbol, conditions))

    def do_show(self, argument):
        """show SYMBOL

        Print the stored alert conditions in the main application output.
        """
        try:
            parts = shlex.split(argument)
        except ValueError as error:
            self._reject(str(error))
            return

        if len(parts) != 1:
            self._reject("usage: show SYMBOL")
            return

        symbol = self._resolve_symbol(parts[0])
        if symbol is None:
            self._reject("unknown symbol: " + parts[0])
            return
        self._send(ShowAlertConditions(symbol))

    def complete_show(self, text, line, begidx, endidx):
        del line, begidx, endidx
        return [symbol for symbol in self.symbols if symbol.startswith(text)]

    def _send(self, command):
        try:
            self.command_client.send(command)
        except OSError as error:
            self._reject("unable to send command: {}".format(error))
            return
        self.stdout.write("sent: {!r}\n".format(command))

    def complete_set(self, text, line, begidx, endidx):
        del endidx
        preceding = line[:begidx].split()
        candidates = self.symbols if len(preceding) <= 1 else self.indicator_names
        return [candidate for candidate in candidates if candidate.startswith(text)]

    def do_symbols(self, argument):
        """List symbols accepted by the CLI."""
        del argument
        self.stdout.write("\n".join(self.symbols) + "\n")

    def do_indicators(self, argument):
        """List exact dataframe indicator names accepted by 'set'."""
        del argument
        self.stdout.write("\n".join(self.indicator_names) + "\n")

    def do_quit(self, argument):
        """Exit the interactive CLI. The market-data application keeps running."""
        del argument
        return True

    def emptyline(self):
        pass

    def _resolve_symbol(self, value):
        candidate = value.upper()
        if candidate in self.symbols:
            return candidate
        if not candidate.startswith("/"):
            candidate = "/" + candidate
        return candidate if candidate in self.symbols else None

    def _reject(self, reason):
        self.stdout.write("rejected: {}\n".format(reason))


def main():
    VwapWaveCli(UnixCommandClient(), SYMBOLS, INDICATOR_COLUMNS).cmdloop()


if __name__ == "__main__":
    main()
