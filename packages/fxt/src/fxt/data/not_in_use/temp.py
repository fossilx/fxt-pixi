

from typing import ClassVar
from pydantic import BaseModel, ConfigDict

class VersionedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    _registry: ClassVar[dict[tuple[str, int], type["VersionedModel"]]] = {}
    _name: ClassVar[str]
    _version: ClassVar[int]

    @classmethod
    def __init_subclass__(cls, *, name: str | None = None,
                                   version: int | None = None, **kwargs):
        super().__pydantic_init_subclass__(**kwargs)
        if name is None:  # intermediate abstract base
            return
        key = (name, version)
        if key in VersionedModel._registry:
            raise ValueError(f"Duplicate model {key}")
        cls._name, cls._version = name, version
        VersionedModel._registry[key] = cls

    @classmethod
    def type_tag(cls) -> str:
        return f"{cls._name}@{cls._version}"

    @classmethod
    def from_tag(cls, tag: str, data: dict) -> "VersionedModel":
        name, version = tag.split("@")
        return cls._registry[(name, int(version))].model_validate(data)

    @classmethod
    def latest(cls, name: str) -> type["VersionedModel"]:
        return max((c for (n, _), c in cls._registry.items() if n == name),
                   key=lambda c: c._version)

#

class TickMetaV1(VersionedModel, name="TickMeta", version=1):
    symbol: str

class TickMetaV2(VersionedModel, name="TickMeta", version=2):
    symbols: list[str]

if __name__ == '__main__':
    from rich import print

    ticks = [
        TickMetaV1(symbol="GBPJPY"),
        TickMetaV2(symbols=["EUR", "USD"])
    ]

    for t in ticks:
        print(f"# {t.__class__.__name__} ~")
    # write
    # meta = {b"meta-type": obj.type_tag().encode(),
    #         b"meta": obj.model_dump_json().encode()}

# read
# md = pq.read_schema(path).metadata
# obj = VersionedModel.from_tag(md[b"meta-type"].decode(),
#                               json.loads(md[b"meta"]))