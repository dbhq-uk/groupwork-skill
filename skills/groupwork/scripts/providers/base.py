"""What a counterpart CLI has to be able to do.

groupwork ships with three providers. The interface exists so that adding a
fourth is a new file rather than a rewrite - but it is deliberately shaped
around what a *second opinion* needs, not around what any one vendor's CLI
happens to offer.

Three functions, and nothing else:

  probe()         - is it installed AND authenticated? Auth is the real barrier
                    to entry; every one of these CLIs installs in a second and
                    then refuses to run.
  capabilities()  - what can it actually do? This is what lets the runner fall
                    back honestly instead of pretending it ran at high effort.
  run()           - do it, write the answer to a file, raise on any failure.

Nothing vendor-specific belongs outside this package. If a flag name, an
environment variable or a quirk of one CLI leaks into the runner, the next
provider inherits it as though it were the contract.
"""

import shutil
import subprocess


class ProviderError(RuntimeError):
    """A provider could not do what was asked, and said why."""


class Provider:
    name = "base"

    #: What this CLI can reach. The runner reads these rather than assuming.
    models: list = []
    efforts: list = []
    sandboxes: list = []
    can_resume = False

    #: Set by a provider that has no way to run without repository access.
    #: red-team defaults to withholding the repo entirely, so a provider that
    #: cannot honour that has to say so rather than quietly read it anyway.
    can_withhold_repo = True

    #: Set where the adapter has never been run against the real CLI - written
    #: from that CLI's documentation and issue tracker rather than from a
    #: working invocation. It surfaces in `groupwork providers` and in the
    #: provenance record, because "this ran through an unverified adapter" is
    #: exactly the sort of thing a citation should carry rather than bury.
    experimental = False

    def __init__(self, config=None):
        self.config = config or {}

    # --- contract -----------------------------------------------------------

    def probe(self):
        """Return the CLI version string, or raise ProviderError with the reason."""
        raise NotImplementedError

    def capabilities(self):
        return {
            "provider": self.name,
            "models": list(self.models),
            "efforts": list(self.efforts),
            "sandboxes": list(self.sandboxes),
            "can_resume": self.can_resume,
            "can_withhold_repo": self.can_withhold_repo,
            "experimental": self.experimental,
        }

    def run(self, brief_path, out_path, model, effort, sandbox, cwd, repo_access=True):
        """Run the brief. Write the response to out_path. Raise on failure."""
        raise NotImplementedError

    def resume(self, brief_path, out_path, cwd):
        """Continue the last session. Providers that cannot, raise."""
        raise ProviderError(f"{self.name} cannot resume a session")

    # --- shared helpers -----------------------------------------------------

    def _which(self, binary):
        found = shutil.which(binary)
        if not found:
            raise ProviderError(
                f"{self.name}: '{binary}' is not on PATH. {self.install_hint()}"
            )
        return found

    def _version(self, argv, timeout=20):
        try:
            done = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            raise ProviderError(f"{self.name}: '{argv[0]} --version' hung") from None
        if done.returncode != 0:
            raise ProviderError(
                f"{self.name}: '{' '.join(argv)}' exited {done.returncode}: "
                f"{(done.stderr or done.stdout).strip()[:300]}"
            )
        return (done.stdout or done.stderr).strip().splitlines()[0]

    def install_hint(self):
        return "See the provider's own install instructions."
