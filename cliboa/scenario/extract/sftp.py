#
# Copyright BrainPad Inc. All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
import os
import re

from cliboa.scenario.base import BaseStep
from cliboa.scenario.validator import EssentialParameters
from cliboa.util.cache import ObjectStore
from cliboa.util.constant import StepStatus
from cliboa.util.sftp import Sftp


class SftpExtract(BaseStep):
    def __init__(self):
        super().__init__()
        self._src_dir = None
        self._src_pattern = None
        self._dest_dir = ""
        self._host = None
        self._port = 22
        self._user = None
        self._password = None
        self._key = None
        self._passphrase = None
        self._endfile_suffix = None
        self._timeout = 30
        self._retry_count = 3

    def src_dir(self, src_dir):
        self._src_dir = src_dir

    def src_pattern(self, src_pattern):
        self._src_pattern = src_pattern

    def dest_dir(self, dest_dir):
        self._dest_dir = dest_dir

    def host(self, host):
        self._host = host

    def port(self, port):
        self._port = port

    def user(self, user):
        self._user = user

    def password(self, password):
        self._password = password

    def key(self, key):
        self._key = key

    def passphrase(self, passphrase):
        self._passphrase = passphrase

    def endfile_suffix(self, endfile_suffix):
        self._endfile_suffix = endfile_suffix

    def timeout(self, timeout):
        self._timeout = timeout

    def retry_count(self, retry_count):
        self._retry_count = retry_count


class SftpDownload(SftpExtract):
    """
    Download files from sftp server
    """

    def __init__(self):
        super().__init__()
        self._quit = False
        self._ignore_empty_file = False

    def quit(self, quit):
        self._quit = quit

    def ignore_empty_file(self, ignore_empty_file):
        self._ignore_empty_file = ignore_empty_file

    def execute(self, *args):
        # essential parameters check
        valid = EssentialParameters(
            self.__class__.__name__,
            [self._host, self._user, self._src_dir, self._src_pattern],
        )
        valid()

        os.makedirs(self._dest_dir, exist_ok=True)

        if isinstance(self._key, str):
            self._logger.warning(
                (
                    "DeprecationWarning: "
                    "In the near future, "
                    "the `key` will be changed to accept only dictionary types. "
                    "Please see more information "
                    "https://github.com/BrainPad/cliboa/blob/master/docs/modules/sftp_download.md"
                )
            )
            key_filepath = self._key
        else:
            key_filepath = self._source_path_reader(self._key)

        # fetch src
        sftp = Sftp(
            self._host,
            self._user,
            self._password,
            key_filepath,
            self._passphrase,
            self._timeout,
            self._retry_count,
            self._port,
        )
        files = sftp.list_files(
            self._src_dir, self._dest_dir,
            re.compile(self._src_pattern),
            self._endfile_suffix,
            self._ignore_empty_file,
        )
        if self._quit is True and len(files) == 0:
            self._logger.info("No file was found. After process will not be processed")
            return StepStatus.SUCCESSFUL_TERMINATION

        self._logger.info("Files downloaded %s" % files)

        # cache downloaded file names
        ObjectStore.put(self._step, files)


class SftpDelete(SftpExtract):
    """
    Delete file from sftp server
    """

    def __init__(self):
        super().__init__()

    def execute(self, *args):
        # essential parameters check
        valid = EssentialParameters(
            self.__class__.__name__,
            [self._host, self._user, self._src_dir, self._src_pattern],
        )
        valid()

        if isinstance(self._key, str):
            self._logger.warning(
                (
                    "DeprecationWarning: "
                    "In the near future, "
                    "the `key` will be changed to accept only dictionary types. "
                    "Please see more information "
                    "https://github.com/BrainPad/cliboa/blob/master/docs/modules/sftp_delete.md"
                )
            )
            key_filepath = self._key
        else:
            key_filepath = self._source_path_reader(self._key)

        # remove src
        sftp = Sftp(
            self._host,
            self._user,
            self._password,
            key_filepath,
            self._passphrase,
            self._timeout,
            self._retry_count,
            self._port,
        )
        sftp.clear_files(self._src_dir, re.compile(self._src_pattern))


class SftpDownloadFileDelete(SftpExtract):
    """
    Delete all downloaded files.
    """

    def __init__(self):
        super().__init__()

    def execute(self, *args):
        files = ObjectStore.get(self._symbol)

        if files is not None and len(files) > 0:
            self._logger.info("Delete files %s" % files)

            if isinstance(super().get_step_argument("key"), str):
                self._logger.warning(
                    (
                        "DeprecationWarning: "
                        "In the near future, "
                        "the `key` will be changed to accept only dictionary types. "
                        "Please see more information "
                        "https://github.com/BrainPad/cliboa/blob/master/docs/modules/sftp_download_file_delete.md"  # noqa
                    )
                )
                key_filepath = super().get_step_argument("key")
            else:
                key_filepath = self._source_path_reader(
                    super().get_step_argument("key")
                )

            sftp = Sftp(
                super().get_step_argument("host"),
                super().get_step_argument("user"),
                super().get_step_argument("password"),
                key_filepath,
                super().get_step_argument("timeout"),
                super().get_step_argument("retry_count"),
                super().get_step_argument("port"),
            )

            endfile_suffix = super().get_step_argument("endfile_suffix")
            for file in files:
                sftp.remove_specific_file(super().get_step_argument("src_dir"), file)
                self._logger.info("%s is successfully deleted." % file)

                if endfile_suffix:
                    sftp.remove_specific_file(
                        super().get_step_argument("src_dir"), file + endfile_suffix)
                    self._logger.info("%s is successfully deleted." % (file + endfile_suffix))
        else:
            self._logger.info("No files to delete.")
