"""Model registry with decorator-based registration."""


class ModelRegistry:
    """Singleton registry for volatility models."""

    _models: dict[str, type] = {}

    @classmethod
    def register(cls, name: str | None = None):
        """Decorator to register a model class."""

        def decorator(model_class):
            key = name or model_class.__name__
            cls._models[key] = model_class
            return model_class

        return decorator

    @classmethod
    def get(cls, name: str) -> type:
        if name not in cls._models:
            raise KeyError(
                f"Model '{name}' not registered. "
                f"Available: {list(cls._models.keys())}"
            )
        return cls._models[name]

    @classmethod
    def list_models(cls) -> list[str]:
        return list(cls._models.keys())

    @classmethod
    def create(cls, name: str, **kwargs):
        """Create a model instance by name."""
        return cls.get(name)(**kwargs)
