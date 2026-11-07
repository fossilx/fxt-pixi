'''
Use this as a sort of log for the files that are downloaded.
'''


#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations

import json
import hashlib
import types
from collections.abc import Iterable, Iterator
from datetime import date, datetime, UTC
from pathlib import Path
from typing import Any, Literal, ClassVar, Self, Union, get_args, get_origin
from dataclasses import dataclass


import sqlite_utils
from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator





#!================================================================================(80)
#! setup (logging, exceptions, etc)
#!--------------------------------------------------------------------------------(80)
import logging
logger = logging.getLogger(__name__)
#logger.setLevel(logging.INFO)

class BadManifest(Exception):
    """
    """
#


#!================================================================================(80)
#! types
#!--------------------------------------------------------------------------------(80)
#re: verification 
ProblemKind = Literal[
    "missing", "size_mismatch", "hash_mismatch",  # file vs. record
    "error_record",                               # ingest logged a failure
    "unaccounted",                                # expected id has no record
    "extra_file",                                 # file on disk, not in manifest
]

@dataclass(frozen=True)
class Problem:
    kind: ProblemKind
    id: str | None = None
    dataset: str | None = None
    detail: str | None = None

#misc
StatusType = Literal['success', 'empty', 'error']


#!================================================================================(80)
#! going from model -> sqlite_utils
#!--------------------------------------------------------------------------------(80)
# python type -> type sqlite_utils understands
_SQLITE_TYPES: dict[type, type] = {
    str: str, int: int, float: float, bool: bool, bytes: bytes,
    datetime: datetime, date: date,
    Path: str,                      # stored as text (model_dump(mode="json") does the same)
}

def _unwrap(tp) -> tuple[type, bool]:
    """ Strip `X | None` and Literal[...]; return (base_type, nullable).
    """
    nullable = False
    if get_origin(tp) in (Union, types.UnionType):
        args = get_args(tp)
        nullable = type(None) in args
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) != 1:
            raise TypeError(f"Unsupported union: {tp}")
        tp = non_none[0]
    if get_origin(tp) is Literal:
        tp = type(get_args(tp)[0])
    return tp, nullable
#

def _get_db_path(db:sqlite_utils.Database):
    """ Get's a database file path from a db object.
    """
    cursor = db.execute("PRAGMA database_list;")
    db_list = cursor.fetchall()

    return next(
        row[2] for row in db_list if row[1] == "main"
    )



#!================================================================================(80)
#! models
#!--------------------------------------------------------------------------------(80)
class FileRecord(BaseModel):
    """ The path should be whatever the parent manifest wants it to be.
    """
    DEFAULT_ALGO:ClassVar[str] = "sha256"

    TABLE:ClassVar[str] = "files"
    PK:ClassVar[str|tuple[str,...]] = ("dataset", "id")


    #~======================================================================(70)
    #~ factory/util
    #~----------------------------------------------------------------------(70)
    @staticmethod
    def HashFile(path:Path, algo:str=DEFAULT_ALGO) -> str:
        """ Provides a consistent way to hash files
        """
        with open(path, "rb") as f:
            digest = hashlib.file_digest(f, algo).hexdigest()

        return digest

    @classmethod
    def FromFile(
        cls,
        dataset:str,
        id:Any,
        root:Path,
        rel_path:Path|None=None,
        rows:int=0,
        algo:str|None=None,
        status:Literal['success', 'empty', 'error']="success",
        error:str|None=None,
        **kw
    ) -> Self:
        """ 
        """
        if(algo is None):
            algo = cls.DEFAULT_ALGO

        #file-related values
        path:Path|None = rel_path
        digest:str|None = None
        size:int|None = None

        if(path is not None):
            full = root / path
            digest = cls.HashFile(full, algo)
            size = full.stat().st_size
        
        return cls(
            dataset=dataset,
            id=id,
            status=status,
            path=path,
            rows=rows,
            algo=algo,
            digest=digest,
            size=size,
            error=error,
            **kw
        )
    #
    @classmethod
    def CreateTable(
        cls,
        db: sqlite_utils.Database,
        table: str|None = None,
        pk = None,
    ) -> sqlite_utils.db.Table:
        """ Create (if missing) the table that stores records of this model.

            Whether a value can be nullable is based on the model. If the model
            field can be None, it is nullable.
        """
        table = table or cls.TABLE
        pk = pk or cls.PK

        columns: dict[str, type] = {}
        not_null: set[str] = set()
        defaults: dict[str, str | int | float] = {}

        for fname, info in cls.model_fields.items():
            base, nullable = _unwrap(info.annotation)
            try:
                columns[fname] = _SQLITE_TYPES[base]
            except KeyError:
                raise TypeError(f"{cls.__name__}.{fname}: no sqlite mapping for {base}")
            
            if not nullable:
                not_null.add(fname)
            # only simple constant defaults; factories (ingested_at) are skipped
            if isinstance(info.default, (str, int, float)):
                defaults[fname] = info.default

        #db name
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "CreateTable (on: %s) -> table: %s"
                "\n - columns: %s"
                "\n - pk: %s"
                "\n - not_null: %s"
                "\n - defaults: %s",
                _get_db_path(db),
                table,
                columns,
                pk,
                not_null,
                defaults
            )
        
        return db.table(table).create(
           columns, 
           pk=pk,
           not_null=not_null,
           defaults=defaults,
           if_not_exists=True
        )
    #

    
    #~======================================================================(70)
    #~ fields
    #~----------------------------------------------------------------------(70)
    dataset:str
    id:str

    #normal fields
    path:Path|None = None
    status:StatusType #Literal["success", "empty", "error"]
    rows:int = 0
    algo:str = DEFAULT_ALGO
    digest:str|None = None
    size:int|None = None
    error:str|None = None
    ingested_at:datetime = Field(default_factory= lambda: datetime.now(tz=UTC))

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v: Any) -> str:
        """
        """
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return str(v)
    #

    @model_validator(mode="after")
    def _check_status(self) -> Self:
        """ Ensure that the combination of (status, digest, rows) is valid.
        """
        if self.status == "success" and (self.path is None or not self.digest or self.rows <= 0):
            raise ValueError("success requires path, digest, and rows > 0")
        if self.status == "empty" and (self.digest or self.rows):
            raise ValueError("empty must have no digest and zero rows")
        if self.status == "error" and not self.error:
            raise ValueError("error requires a message")
        return self
    #

    #~======================================================================(70)
    #~ re: verification 
    #~----------------------------------------------------------------------(70)
    def check_file(self, root: Path, check_hash: bool = True) -> ProblemKind|None:
        """ Compare the file on disk to this record.

            Returns None if OK (or if there is no file to check), otherwise
            one of: "missing", "size_mismatch", "hash_mismatch".
        """
        if self.status != "success" or self.path is None:
            return None

        full = root / self.path
        if not full.is_file():
            return "missing"
        if self.size is not None and full.stat().st_size != self.size:
            return "size_mismatch"
        if check_hash and self.HashFile(full, self.algo) != self.digest:
            return "hash_mismatch"
        return None
    #

#-

class FinancialFileRecord(FileRecord):
    """
    """
    TABLE:ClassVar[str] = "financial_files"

    #additional fields
    first_ts: datetime|None = Field(
        default=None,
        description="First timestamp covered by this file."
    )
    last_ts: datetime|None = Field(
        default=None,
        description="Last timestamp covered by this file."
    )
#-




#!================================================================================(80)
#! manifest
#!--------------------------------------------------------------------------------(80)
from typing import Generic, TypeVar
TRecord = TypeVar("TRecord", bound=FileRecord)

class Manifest(BaseModel, Generic[TRecord]):
    """ For a given directory, designed to store details about the files/contents
        of that directory. It is meant to act as a sort of "log" to keep track of
        how things worked when the files were first created. 

        TODO:
        - if needed in future, figure out a way to save/load custom settings
          I dont need this yet though.
    """
    path:Path = Field(description="Path to this manifest file.")
    record_type: type[TRecord] = Field(exclude=True)

    
    #! private
    _db: sqlite_utils.Database = PrivateAttr()

    @property
    def root(self) -> Path:
        """ Corresponds to the directory containing this manifest.
            Useful for verification.
        """
        return self.path.parent
    #

    @property
    def _table_name(self) -> str:
        return self.record_type.TABLE
    #
    @property
    def _table(self):
        return self._db.table(self._table_name)
    #
    @property
    def _pk(self):
        return self.record_type.PK
    #

    def model_post_init(self, __context: Any, /) -> None:
        """
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite_utils.Database(self.path)
        # self._db.enable_wal()
        # self.record_type.CreateTable(self._db)
        try:
            self._db.enable_wal()
            self._check_compatible()
            self.record_type.CreateTable(self._db)
        except BadManifest:
            self._db.close()
            raise
    #

    def _check_compatible(self) -> None:
        """ Refuse to open a db that was made for a different record type.
            Runs before CreateTable so a wrong open doesn't add a stray table.
        """
        # a manifest directory holds one record type's table
        others = [
            t for t in self._db.table_names()
            if t != self._table_name and not t.startswith("sqlite_")
        ]
        if others:
            raise BadManifest(
                f"{self.path} has table(s) {others}, but "
                f"{self.record_type.__name__} uses '{self._table_name}'"
            )

        # same table name, but columns the model doesn't know about
        table = self._table
        if table.exists():
            unknown = set(table.columns_dict) - set(self.record_type.model_fields)
            if unknown:
                raise BadManifest(
                    f"'{self._table_name}' in {self.path} has columns not in "
                    f"{self.record_type.__name__}: {sorted(unknown)}"
                )
    #

    #~======================================================================(70)
    #~ context manager support
    #~----------------------------------------------------------------------(70)
    def __enter__(self) -> Self:
        """
        """
        return self
    #

    def __exit__(self, exc_type, exc, tb) -> None:
        """
        """
        self.close()
    #
    
    def close(self) -> None:
        """ Call this manually if needed. It's probably easier to use a context 
            manager to handle this.
        """
        self._db.close()
    #

    #~======================================================================(70)
    #~ adding record
    #~----------------------------------------------------------------------(70)
    def add(self, record:TRecord):
        """ adds/inserts a record into the target table.
        """
        self._table.upsert(
            record.model_dump(mode="json"),
            pk=self._pk,
            alter=True #add missing columns if needed
        )
    #

    def find(self, **where: Any) -> list[TRecord]: #Iterator[TRecord]:
        """ Returns an instance of the row's record type.
        """
        unknown = where.keys() - self.record_type.model_fields.keys()
        if unknown:
            raise KeyError(f"Unknown columns: {sorted(unknown)}")

        results = []
        clause = " AND ".join(f"[{c}] = ?" for c in where) or None
        for row in self._table.rows_where(clause, list(where.values())):
            #yield self.record_type.model_validate(row)
            results.append(self.record_type.model_validate(row))
        
        return results
    #

    def get(self, *, dataset:str, id:str) -> TRecord|None:
        """ Get's row based on the provided primary key.
        """
        #return next(self.find(dataset=dataset, id=id), None)
        results = self.find(dataset=dataset, id=id)
        return results[0] if results else None
    #



    #~======================================================================(70)
    #~ verification
    #~----------------------------------------------------------------------(70)
    def verify(
        self,
        dataset: str | None = None,
        *,
        check_hash: bool = True,
        expected_ids: Iterable[Any] | None = None,
        check_extra: bool = False,
    ) -> list[Problem]:
        """ Verify the directory against this manifest. Returns a list of
            problems; an empty list means everything checked out.

            check_hash:   False does a fast existence + size check only.
            expected_ids: ids (str or date) that must have a record, e.g. every
                          trading day in the month. Requires `dataset`.
            check_extra:  also report files in the directory that no record
                          (of any dataset) points to.
        """
        problems: list[Problem] = []
        records = self.find(dataset=dataset) if dataset else self.find()

        for rec in records:
            if rec.status == "error":
                problems.append(Problem("error_record", rec.id, rec.dataset, rec.error))
                continue
            kind:ProblemKind|None = rec.check_file(self.root, check_hash=check_hash)
            if kind is not None:
                problems.append(Problem(kind, rec.id, rec.dataset, str(rec.path)))

        if expected_ids is not None:
            if dataset is None:
                raise ValueError("expected_ids requires a dataset")
            seen = {r.id for r in records}
            wanted = {
                v.isoformat() if isinstance(v, (date, datetime)) else str(v)
                for v in expected_ids
            }
            problems.extend(
                Problem("unaccounted", id_, dataset) for id_ in sorted(wanted - seen)
            )

        if check_extra:
            # use all records here, not just the filtered ones, so files that
            # belong to other datasets aren't reported as extra
            tracked = {
                (self.root / r.path).resolve()
                for r in self.find() if r.path is not None
            }
            ignore = {self.path.name, f"{self.path.name}-wal", f"{self.path.name}-shm"}
            for p in sorted(self.root.rglob("*")):
                if p.is_file() and p.name not in ignore and p.resolve() not in tracked:
                    problems.append(
                        Problem("extra_file", detail=str(p.relative_to(self.root)))
                    )

        return problems
    #
#-



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from fxt.term import hr
    from rich import print
    from rich.panel import Panel
    from datetime import date
    from pprint import pprint, pformat

    TEST_OUTPUT_ROOT = Path(".tmp/manifests")

    # def test_create_table():
    #     path = TEST_OUTPUT_ROOT / "test-create-table.db"
    #     path.parent.mkdir(parents=True, exist_ok=True)

    #     db = sqlite_utils.Database(path)

    #     #FileRecord
    #     FinancialFileRecord.CreateTable(db)
    # #
    # test_create_table()


    import random
    from datetime import time, timedelta, date, datetime, UTC
    def make_test_manifest(
        dest: Path,
        dataset: str = "FAKUSD",
        year: int = 2024,
        month: int = 1,
        *,
        seed: int = 0,
        plant_problems: bool = True,
    ) -> dict[str, list[str]]:
        """ Create fake daily files plus a manifest.db in `dest`.

            Saturdays get no record or file (your "not required" rule). A couple of
            weekdays are recorded as "empty" and one as "error". If plant_problems
            is True, a few more days are damaged in specific ways.

            Returns {problem_kind: [ids]} describing what verify() should report.
        """
        rng = random.Random(seed)
        dest.mkdir(parents=True, exist_ok=True)

        # every non-Saturday in the month
        days: list[date] = []
        d = date(year, month, 1)
        while d.month == month:
            if d.weekday() != 5:
                days.append(d)
            d += timedelta(days=1)

        # assign roles to distinct random days
        roles = ["empty", "empty", "error"]
        if plant_problems:
            roles += ["missing", "size_mismatch", "hash_mismatch", "unaccounted"]
        role_of = dict(zip(rng.sample(days, len(roles)), roles))

        expected: dict[str, list[str]] = {}

        def expect(kind: str, what: str) -> None:
            expected.setdefault(kind, []).append(what)

        with Manifest(path=dest / "manifest.db", record_type=FinancialFileRecord) as m:
            for d in days:
                role = role_of.get(d, "ok")
                id_ = d.isoformat()

                if role == "unaccounted":
                    expect("unaccounted", id_)
                    continue  # no file, no record

                if role == "empty":
                    m.add(FinancialFileRecord(dataset=dataset, id=d, status="empty"))  # type: ignore
                    continue

                if role == "error":
                    m.add(FinancialFileRecord(
                        dataset=dataset, id=d, status="error",   # type: ignore
                        error="simulated download failure",
                    ))
                    expect("error_record", id_)
                    continue

                # success: write a fake file and record it (hash is taken from the
                # pristine file, so any damage below is detected later)
                rel = Path(f"{dataset}-{id_}.parquet")
                full = dest / rel
                full.write_bytes(rng.randbytes(rng.randint(200, 2000)))
                m.add(FinancialFileRecord.FromFile(
                    dataset=dataset, id=d, root=dest, rel_path=rel,
                    rows=rng.randint(1_000, 50_000),
                    first_ts=datetime.combine(d, time.min, UTC),
                    last_ts=datetime.combine(d, time(23, 59, 59), UTC),
                ))

                if role == "missing":
                    full.unlink()
                    expect("missing", id_)
                elif role == "size_mismatch":
                    with full.open("ab") as f:
                        f.write(b"extra")
                    expect("size_mismatch", id_)
                elif role == "hash_mismatch":
                    data = bytearray(full.read_bytes())
                    data[0] ^= 0xFF  # same size, different content
                    full.write_bytes(bytes(data))
                    expect("hash_mismatch", id_)

        if plant_problems:
            (dest / "stray.txt").write_text("not in the manifest")
            expect("extra_file", "stray.txt")

        return expected
    #

    def test_testenv(dataset="FAKUSD"):
        #test folder
        dest = TEST_OUTPUT_ROOT / "testenvs" / dataset
        expected = make_test_manifest(dest, dataset=dataset)

        #! define what days are expected to exist
        days = []
        d = date(2024, 1, 1)
        while d.month == 1:
            if d.weekday() != 5:
                days.append(d)
            d += timedelta(days=1)

        with Manifest(path=dest / "manifest.db", record_type=FinancialFileRecord) as m:
            problems = m.verify(dataset, expected_ids=days, check_extra=True)


        got: dict[str, list[str]] = {}
        for p in problems:
            got.setdefault(p.kind, []).append(p.detail if p.kind == "extra_file" else p.id) # type: ignore

        assert {k: sorted(v) for k, v in got.items()} == {k: sorted(v) for k, v in expected.items()}
    #




    test_testenv()









    # example = "downloads/EURJPY/TICK/2024/01/manifest.db"


    # def test_queries(mani:Path|str):
    #     """
    #     """
        
    #     with Manifest(path=Path(mani), key="day") as manifest:
    #         print(Panel(repr(manifest), title="", title_align="left"))

    #         #! selecting a 
    #         print(Panel((
    #                 f"\n- [green]getting an existing day[/]: {manifest.get(date(2024,1,2).isoformat())}"
    #                 f"\n- [green]getting a non-existant day[/]: {manifest.get(date(2027,1,2).isoformat())}"
    #             ),
    #             title="[cyan]SELECTING [bold]SINGLE[/] ENTRIES[/]",
    #             title_align="left"
    #         ))

    #         #! try looping through rows
    #         rows_str = ""
    #         for row in manifest.rows():
    #             rows_str += f"\n* [green]row[/]: {row}"
    #         print(Panel(rows_str, title="[cyan]LIST [bold]ALL[/] ROWS[/]", title_align="left"))


    #         #! try looping through rows + pk
    #         rows_str = ""
    #         for pk, row in manifest.all():
    #             rows_str += f"\n* [[green]{pk}[/]] ~ {row}"
    #         print(Panel(rows_str, title="[cyan]LIST ALL ROWS[bold]+ PKS[/][/]", title_align="left"))


    #         #! now select a subset
    #         subset = { 'status': "empty" }
    #         rows_str = ""
    #         for pk, row in manifest.find(**subset):
    #             rows_str += f"\n* [[green]{pk}[/]]: {row}"
    #         print(Panel(rows_str, title="[cyan]SELECT A [bold]SUBSET[/][/]", title_align="left"))
    # #

    #test_queries(example)

    # def test_factory(mani:Path|str):
    #     """
    #     """
    #     manifest = Manifest.FromFile(Path(mani))

    #     print(Panel((
    #             f"{mani}"
    #             #f"\n- [green]getting an existing day[/]: {manifest.get(date(2024,1,2).isoformat())}"
    #             #f"\n- [green]getting a non-existant day[/]: {manifest.get(date(2027,1,2).isoformat())}"
    #         ),
    #         title="[cyan]Initializing existing manifest from...[/]",
    #         title_align="left"
    #     ))

    #     meta = manifest.meta()
    #     print(Panel((
    #             f"[green]type[/]: {type(meta)}"
    #             f"[green]values[/]:\n{pformat(meta, indent=4)}"

    #             #f"\n- [green]getting an existing day[/]: {manifest.get(date(2024,1,2).isoformat())}"
    #             #f"\n- [green]getting a non-existant day[/]: {manifest.get(date(2027,1,2).isoformat())}"
    #         ),
    #         title="[cyan]manfiest meta[/]",
    #         title_align="left"
    #     ))



    #     #manifest
    # #


    # test_factory(example)