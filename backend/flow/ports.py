"""What the flow needs from outside: a language model and the profile/order store.

The presentation layer plugs its provider in at startup (backend/presentation/main.py → ports.use(product)),
so the flow never imports presentation. Calls look the provider's attributes up each time, so tests that
monkeypatch product.llm / product.store keep working.
"""
_provider = None


def use(provider):
    global _provider
    _provider = provider


def _wired():
    if _provider is None:
        raise RuntimeError('backend.flow.ports is not wired: call ports.use(provider) at startup')
    return _provider


def configured():
    return _provider is not None and _provider.configured()


async def llm(system, messages):
    return await _wired().llm(system, messages)


async def parse(text):
    provider = _wired()
    return await provider.parse(provider.TextInput(text=text))


def store():
    return _wired().store
