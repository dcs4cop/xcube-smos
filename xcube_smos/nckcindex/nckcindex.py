# The MIT License (MIT)
# Copyright (c) 2023 by the xcube development team and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

import json
from pathlib import Path
from typing import Union, Dict, Any, Optional, Iterator, List, \
    Tuple, TypeVar, Type
import string
import os
import warnings

import fsspec
from .constants import INDEX_CONFIG_FILENAME
from .constants import INDEX_CONFIG_VERSION

AFS = fsspec.AbstractFileSystem


class NcKcIndex:
    """
    Represents a NetCDF Kerchunk index.
    """

    def __init__(self,
                 index_fs: AFS,
                 index_path: str,
                 index_protocol: str,
                 index_config: Dict[str, Any]):
        """
        Private constructor. Use :meth:create() or :meth:open() instead.

        :param index_fs: Index filesystem.
        :param index_path: Path to the index directory.
        :param index_protocol: The protocol used by the index filesystem.
        :param index_config: Optional storage options for accessing the
            filesystem of *index_path*.
            See fsspec for protocol given by *index_urlpath*.
        """
        self.index_fs = index_fs
        self.index_path = index_path
        self.index_protocol = index_protocol
        self.index_config = index_config

        self.source_path = _get_config_param(index_config, "source_path")
        self.source_protocol = _get_config_param(
            index_config,
            "source_protocol", str,
            fsspec.core.split_protocol(self.source_path)[0] or "file"
        )
        self.source_storage_options = _get_config_param(
            index_config,
            "source_storage_options", dict,
            {}
        )
        self.source_fs = fsspec.filesystem(self.source_protocol,
                                           **self.source_storage_options)
        self.is_closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        self.close()

    def close(self):
        if not self.is_closed:
            self.close_fs(self.index_fs)
            self.close_fs(self.source_fs)
            self.is_closed = True

    @classmethod
    def close_fs(cls, fs: AFS):
        if hasattr(fs, "close"):
            # noinspection PyBroadException
            try:
                fs.close()
            except BaseException:
                pass

    @classmethod
    def create(
            cls,
            index_path: Union[str, Path],
            index_protocol: Optional[str] = None,
            index_storage_options: Optional[Dict[str, Any]] = None,
            source_path: Optional[Union[str, Path]] = None,
            source_protocol: Optional[str] = None,
            source_storage_options: Optional[Dict[str, Any]] = None,
            replace: bool = False,
    ) -> "NcKcIndex":
        """
        Create a new NetCDF Kerchunk index.

        :param index_path: The index path or URL.
        :param index_protocol: The index protocol.
            If not provided, it will be derived from *index_path*.
        :param index_storage_options: Optional storage options for accessing
            the filesystem of *index_path*.
            See Python fsspec package spec for the used index protocol.
        :param source_path: The source path or URL.
        :param source_protocol: Optional protocol for the source filesystem.
            If not provided, it will be derived from *source_path*.
        :param source_storage_options: Storage options for source
            NetCDF files, e.g., options for an S3 filesystem,
            See Python fsspec package spec for the used source protocol.
        :param replace: Whether to replace an existing
            NetCDF Kerchunk index.
        :return: A new NetCDF file index.
        """
        if not source_path:
            raise ValueError("Missing source_path")

        source_storage_options = source_storage_options or {}
        source_path, source_protocol = _normalize_path_protocol(
            source_path,
            protocol=source_protocol
        )

        index_config = dict(
            version=INDEX_CONFIG_VERSION,
            source_path=source_path,
            source_protocol=source_protocol,
            source_storage_options=source_storage_options,
        )

        index_fs, index_path, _ = _open_index_fs(
            index_path,
            mode="x",  # x = create
            replace=replace,
            protocol=index_protocol,
            storage_options=index_storage_options,
        )
        with index_fs.open(INDEX_CONFIG_FILENAME, "w") as fp:
            json.dump(index_config, fp, indent=2)
        cls.close_fs(index_fs)

        return cls.open(index_path,
                        index_protocol=index_protocol,
                        index_storage_options=index_storage_options,
                        mode="w")

    @classmethod
    def open(
            cls,
            index_path: Union[str, Path],
            index_protocol: Optional[str] = None,
            index_storage_options: Optional[Dict[str, Any]] = None,
            mode: str = "r"
    ) -> "NcKcIndex":
        """Open the given index at *index_path*.

        :param index_path: The index path or URL.
        :param index_protocol: The index protocol.
            If not provided, it will be derived from *index_path*.
        :param index_storage_options: Optional storage options for accessing
            the filesystem of *index_path*.
            See Python fsspec package spec for the used index protocol.
        :param mode: Open mode, must be either "w" or "r".
            Defaults to "r".
        :return: A NetCDF file index.
        """
        if mode not in ("r", "w"):
            raise ValueError("Invalid mode, must be either 'r' or 'w'")

        # Open with "r" mode, so we can read configuration
        index_fs, index_path, index_protocol = _open_index_fs(
            index_path,
            mode="r",
            protocol=index_protocol,
            storage_options=index_storage_options,
        )
        with index_fs.open(INDEX_CONFIG_FILENAME, "r") as f:
            index_config = _substitute_json(json.load(f))

        if mode == "w":
            cls.close_fs(index_fs)
            # Reopen using write mode
            index_fs, index_path, index_protocol = _open_index_fs(
                index_path,
                mode=mode,
                protocol=index_protocol,
                storage_options=index_storage_options,
            )

        return NcKcIndex(
            index_fs,
            index_path,
            index_protocol,
            index_config
        )

    def sync(self,
             prefix: Optional[str] = None,
             num_workers: int = 1,
             block_size: int = 100,
             force: bool = False,
             dry_run: bool = False) -> Tuple[int, List[str]]:
        """Synchronize this index with the files.
        If *prefix* is given, only files that match the given prefix
        are processed. Otherwise, all SMOS L2 files are processed.

        :param prefix: Key prefix.
        :param num_workers: Number of parallel workers.
            Not used yet.
        :param block_size: Number of files processed by a single worker.
            Ignored, if *num_workers* is less than two.
            Not used yet.
        :param force: Do not skip existing indexes.
        :param dry_run: Do not write any indexes. Useful for testing.
        :return: A tuple comprising the number of NetCDF files
            successfully indexed and a list of encountered problems.
        """
        problems = []
        num_files = 0
        if num_workers < 2:
            for nc_file in self.get_nc_files(prefix=prefix):
                problem = self.index_nc_file(
                    nc_file, force=force, dry_run=dry_run
                )
                if problem is None:
                    num_files += 1
                else:
                    problems.append(problem)
        else:
            # TODO: setup mult-threaded/-process (Dask) executor with
            #   num_workers and submit workload in blocks. [#12]
            warnings.warn(f'num_workers={num_workers}:'
                          f' parallel processing not implemented yet.')
            for nc_file_block in self.get_nc_file_blocks(
                    prefix=prefix, block_size=block_size
            ):
                for nc_file in nc_file_block:
                    problem = self.index_nc_file(
                        nc_file, force=force, dry_run=dry_run
                    )
                    if problem is None:
                        num_files += 1
                    else:
                        problems.append(problem)
        return num_files, problems

    def get_nc_files(self,
                     prefix: Optional[str] = None) -> Iterator[str]:

        source_fs = self.source_fs
        source_path = self.source_path

        if prefix:
            source_path += "/" + prefix

        def handle_error(e: OSError):
            print(f"Error scanning source {source_path}:"
                  f" {e.__class__.__name__}: {e}")

        for path, _, files in source_fs.walk(source_path,
                                             on_error=handle_error):
            for file in files:
                if file.endswith(".nc"):
                    yield path + "/" + file

    def get_nc_file_blocks(self,
                           prefix: Optional[str] = None,
                           block_size: int = 100) -> Iterator[List[str]]:
        block = []
        for nc_file in self.get_nc_files(prefix=prefix):
            block.append(nc_file)
            if len(block) >= block_size:
                yield block
                block = []
        if block:
            yield block

    def index_nc_file(self,
                      nc_source_path: str,
                      force: bool = False,
                      dry_run: bool = False) -> Optional[str]:
        """
        Index a NetCDF file given by *nc_path* in S3.

        :param nc_source_path: NetCDF source file path.
        :param force: Do not skip existing indexes.
        :param dry_run: Do not write any indexes. Useful for testing.
        :return: None, if the NetCDF file has been successfully indexed.
            Otherwise, a message indicating the problem.
        """
        import kerchunk.hdf

        if nc_source_path.startswith(self.source_path + "/"):
            nc_source_rel_path = nc_source_path[(len(self.source_path) + 1):]
        else:
            nc_source_rel_path = nc_source_path

        nc_index_path = f"{nc_source_rel_path}.json"

        if not force and self.index_fs.exists(nc_index_path):
            print(f"Skipping {nc_source_path}, index exists")
            return None

        print(f"Indexing {nc_source_path}")

        try:
            with self.source_fs.open(nc_source_path, mode="rb") as f:
                chunks = kerchunk.hdf.SingleHdf5ToZarr(
                    f, nc_source_path, inline_threshold=100
                )
                chunks_object = chunks.translate()
        except OSError as e:
            problem = f"Error indexing {nc_source_path}:" \
                      f" {e.__class__.__name__}: {e}"
            print(problem)
            return problem

        if dry_run:
            return None

        nc_index_dir, _ = _split_parent_dir(nc_index_path)
        try:
            self.index_fs.mkdirs(nc_index_dir, exist_ok=True)
            with self.index_fs.open(nc_index_path, "w") as f:
                json.dump(chunks_object, f)
        except OSError as e:
            problem = f"Error writing index {nc_index_path}:" \
                      f" {e.__class__.__name__}: {e}"
            print(problem)
            return problem

        return None


T = TypeVar('T')
_UNDEFINED = "_UNDEFINED"


def _get_config_param(index_config: Dict[str, Any],
                      param_name: str,
                      param_type: Type[T] = str,
                      default_value: Any = _UNDEFINED) -> T:
    if param_name not in index_config:
        if default_value == _UNDEFINED:
            raise ValueError(f"Missing configuration "
                             f"parameter '{param_name}'")
        return default_value
    value = index_config.get(param_name)
    if not isinstance(value, param_type):
        raise ValueError(f"Configuration parameter '{param_name}' "
                         f"must be of type {param_type}, "
                         f"but was {type(value)}")
    return value


def _open_index_fs(
        path: str | Path,
        mode: str,
        replace: bool = False,
        protocol: Optional[str] = None,
        storage_options: Optional[Dict[str, Any]] = None
) -> Tuple[AFS, str, str]:
    if path.endswith(".zip"):
        return _open_zip_fs(path, mode, replace, protocol, storage_options)
    else:
        return _open_dir_fs(path, mode, replace, protocol, storage_options)


def _open_zip_fs(
        path: str | Path,
        mode: str,
        replace: bool = False,
        protocol: Optional[str] = None,
        storage_options: Optional[Dict[str, Any]] = None
) -> Tuple[AFS, str, str]:
    base_fs, path, protocol = _get_fs_path_protocol(path, protocol,
                                                    storage_options)
    zip_exists = base_fs.isfile(path)
    if mode == "x":
        if zip_exists:
            if replace:
                base_fs.delete(path)
            else:
                raise OSError(f"File exists: {path}")
        parent_dir, _ = _split_parent_dir(path)
        if not base_fs.exists(parent_dir):
            base_fs.mkdirs(parent_dir, exist_ok=True)
    else:  # elif mode in ("w", "r"):
        if not zip_exists:
            raise FileNotFoundError(f"File not found: {path}")
    zip_fs = fsspec.filesystem("zip",
                               fo=path,
                               mode="a" if mode in ("x", "w") else "r",
                               target_protocol=protocol,
                               target_options=storage_options)
    return zip_fs, path, protocol


def _open_dir_fs(
        path: str | Path,
        mode: str,
        replace: bool = False,
        protocol: Optional[str] = None,
        storage_options: Optional[Dict[str, Any]] = None
) -> Tuple[AFS, str, str]:
    base_fs, path, protocol = _get_fs_path_protocol(path, protocol,
                                                    storage_options)
    dir_exists = base_fs.isdir(path)
    if mode == "x":
        if dir_exists:
            if replace:
                base_fs.delete(path, recursive=True)
                dir_exists = False
            else:
                raise OSError(f"Directory exists: {path}")
        if not dir_exists:
            base_fs.makedirs(path, exist_ok=True)
    else:  # elif mode in ("w", "r"):
        if not dir_exists:
            raise FileNotFoundError(f"Directory not found: {path}")
    dir_fs = fsspec.filesystem("dir", fo=path, fs=base_fs)
    return dir_fs, path, protocol


def _get_fs_path_protocol(path: str,
                          protocol: str,
                          storage_options: Dict[str, Any]) \
        -> Tuple[AFS, str, str]:
    path, protocol = _normalize_path_protocol(path, protocol)
    fs = fsspec.filesystem(protocol,
                           **(storage_options or {}))
    return fs, path, protocol


def _normalize_path_protocol(
        path: str | Path,
        protocol: Optional[str] = None,
) -> Tuple[str, str]:
    _protocol, path = fsspec.core.split_protocol(path)
    protocol = protocol or _protocol or "file"
    if os.name == "nt" and protocol in ("file", "local"):
        # Normalize a Windows path
        path = path.replace("\\", "/")
    return path, protocol


def _split_parent_dir(path: str) -> Tuple[str, str]:
    splits = path.rsplit("/", maxsplit=1)
    if len(splits) == 1:
        return "", path
    return splits[0], splits[1]


def _substitute_json(value: Any) -> Any:
    if isinstance(value, str):
        return _substitute_text(value)
    if isinstance(value, dict):
        return {_substitute_text(k): _substitute_json(v) for k, v in
                value.items()}
    if isinstance(value, list):
        return [_substitute_json(v) for v in value]
    return value


def _substitute_text(text: str) -> str:
    return string.Template(text).safe_substitute(os.environ)
