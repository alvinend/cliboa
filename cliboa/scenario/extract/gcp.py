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
import json
import os
import random
import re
import string
from datetime import datetime

import pandas
from google.cloud import bigquery

from cliboa.scenario.gcp import BaseBigQuery, BaseFirestore, BaseGcs
from cliboa.scenario.validator import EssentialParameters
from cliboa.util.cache import ObjectStore
from cliboa.util.exception import InvalidParameter
from cliboa.util.gcp import BigQuery, Firestore, Gcs, ServiceAccount
from cliboa.util.string import StringUtil


class BigQueryRead(BaseBigQuery):
    """
    Read data from BigQuery and put them into on-memory or export to a file via GCS.
    """

    _RANDOM_STR_LENGTH = 8

    def __init__(self):
        super().__init__()
        self._key = None
        self._bucket = None
        self._dest_dir = None
        self._filename = None
        self._query = None

    def key(self, key):
        self._key = key

    def query(self, query):
        self._query = query

    def bucket(self, bucket):
        self._bucket = bucket

    def dest_dir(self, dest_dir):
        self._dest_dir = dest_dir

    def filename(self, filename):
        self._filename = filename

    def execute(self, *args):
        super().execute()
        if not self._key and not self._bucket:
            raise InvalidParameter("Specifying either 'key' or 'bucket' is essential.")
        if self._key and self._bucket:
            raise InvalidParameter("Cannot specify both 'key' and 'bucket'.")

        # fetch records and save to on-memory
        if self._key:
            valid = EssentialParameters(self.__class__.__name__, [self._tblname])
            valid()
            self._save_to_cache()
        elif self._bucket:
            valid = EssentialParameters(self.__class__.__name__, [self._dest_dir])
            valid()
            self._save_as_file_via_gcs()

    def _save_to_cache(self):
        self._logger.info("Save data to on memory")
        if isinstance(self._credentials, str):
            self._logger.warning(
                (
                    "DeprecationWarning: "
                    "In the near future, "
                    "the `credentials` will be changed to accept only dictionary types. "
                    "Please see more information "
                    "https://github.com/BrainPad/cliboa/blob/master/docs/modules/bigquery_read.md"
                )
            )
            key_filepath = self._credentials
        else:
            key_filepath = self._source_path_reader(self._credentials)
        df = pandas.read_gbq(
            query="SELECT * FROM %s.%s" % (self._dataset, self._tblname)
            if self._query is None
            else self._query,
            dialect="standard",
            location=self._location,
            project_id=self._project_id,
            credentials=ServiceAccount.auth(key_filepath),
        )
        ObjectStore.put(self._key, df)

    def _save_as_file_via_gcs(self):
        self._logger.info("Save data as a file via GCS")
        os.makedirs(self._dest_dir, exist_ok=True)

        ymd_hms = datetime.now().strftime("%Y%m%d%H%M%S%f")
        path = "%s-%s" % (StringUtil().random_str(self._RANDOM_STR_LENGTH), ymd_hms,)
        prefix = "%s/%s/%s" % (self._dataset, self._tblname, path)

        if isinstance(self._credentials, str):
            self._logger.warning(
                (
                    "DeprecationWarning: "
                    "In the near future, "
                    "the `credentials` will be changed to accept only dictionary types. "
                    "Please see more information "
                    "https://github.com/BrainPad/cliboa/blob/master/docs/modules/bigquery_read.md"
                )
            )
            key_filepath = self._credentials
        else:
            key_filepath = self._source_path_reader(self._credentials)
        gbq_client = BigQuery.get_bigquery_client(key_filepath)
        if self._dataset and self._tblname:
            table_ref = gbq_client.dataset(self._dataset).table(self._tblname)
        elif self._dataset and not self._tblname:
            tmp_tbl = (
                "tmp_"
                + StringUtil().random_str(self._RANDOM_STR_LENGTH)
                + "_"
                + ymd_hms
            )
            table_ref = gbq_client.dataset(self._dataset).table(tmp_tbl)
        gcs_client = Gcs.get_gcs_client(key_filepath)
        gcs_bucket = gcs_client.bucket(self._bucket)

        # extract job config settings
        ext_job_config = BigQuery.get_extract_job_config()
        ext_job_config.compression = BigQuery.get_compression_type()
        ext = ".csv"
        if self._filename:
            _, ext = os.path.splitext(self._filename)
            support_ext = [".csv", ".json"]
            if ext not in support_ext:
                raise InvalidParameter("%s is not supported as filename." % ext)
        ext_job_config.destination_format = BigQuery.get_destination_format(ext)

        comp_format_and_ext = {"GZIP": ".gz"}
        comp_ext = comp_format_and_ext.get(str(BigQuery.get_compression_type()))
        if self._filename:
            dest_gcs = "gs://%s/%s/%s%s" % (
                self._bucket,
                prefix,
                self._filename,
                comp_ext,
            )
        else:
            dest_gcs = "gs://%s/%s/*%s%s" % (self._bucket, prefix, ext, comp_ext)

        # Execute query.
        if self._query:
            query_job_config = BigQuery.get_query_job_config()
            query_job_config.destination = table_ref
            query_job_config.write_disposition = BigQuery.get_write_disposition()
            query_job = gbq_client.query(
                self._query, location=self._location, job_config=query_job_config
            )
            query_job.result()

        # Extract to GCS
        extract_job = gbq_client.extract_table(
            table_ref, dest_gcs, job_config=ext_job_config, location=self._location
        )
        extract_job.result()

        # Download from gcs
        for blob in gcs_bucket.list_blobs(prefix=prefix):
            dest = os.path.join(self._dest_dir, os.path.basename(blob.name))
            blob.download_to_filename(dest)

        # Cleanup temporary table
        if self._query:
            gbq_client.delete_table(table_ref)

        # Cleanup temporary files
        for blob in gcs_bucket.list_blobs(prefix=prefix):
            blob.delete()


class BigQueryReadCache(BaseBigQuery):
    """
    @deprecated
    Please Use BigQueryRead instead.

    Get data from BigQuery and cache them as pandas.dataframe format.

    Use {BigQueryFileDownload} if the result query is estimated to be large.
    """

    def __init__(self):
        super().__init__()
        self._key = None
        self._query = None

    def key(self, key):
        self._key = key

    def query(self, query):
        self._query = query

    def _get_query(self):
        if self._query is None:
            return "SELECT * FROM %s.%s" % (self._dataset, self._tblname)
        else:
            return self._query

    def execute(self, *args):
        self._logger.warning("Deprecated. Please Use BigQueryRead instead.")

        super().execute()
        valid = EssentialParameters(self.__class__.__name__, [self._key])
        valid()

        if isinstance(self._credentials, str):
            self._logger.warning(
                (
                    "DeprecationWarning: "
                    "In the near future, "
                    "the `credentials` will be changed to accept only dictionary types. "
                )
            )
            key_filepath = self._credentials
        else:
            key_filepath = self._source_path_reader(self._credentials)
        df = pandas.read_gbq(
            query=self._get_query(),
            dialect="standard",
            location=self._location,
            project_id=self._project_id,
            credentials=ServiceAccount.auth(key_filepath),
        )
        ObjectStore.put(self._key, df)


class BigQueryFileDownload(BaseBigQuery):
    """
    @deprecated
    Please Use BigQueryRead instead.

    Download query result as a csv file.

    This class saves BigQuery result as a temporary file in GCS, and then download.
    Download file could be a multiple if file size exceed 1GB.
    """

    def __init__(self):
        super().__init__()
        self._bucket = None
        self._dest_dir = None
        self._filename = None

    def bucket(self, bucket):
        self._bucket = bucket

    def dest_dir(self, dest_dir):
        self._dest_dir = dest_dir

    def filename(self, filename):
        self._filename = filename

    def execute(self, *args):
        self._logger.warning("Deprecated. Please Use BigQueryRead instead.")

        super().execute()

        valid = EssentialParameters(
            self.__class__.__name__, [self._tblname, self._bucket, self._dest_dir]
        )
        valid()

        os.makedirs(self._dest_dir, exist_ok=True)

        if isinstance(self._credentials, str):
            self._logger.warning(
                (
                    "DeprecationWarning: "
                    "In the near future, "
                    "the `credentials` will be changed to accept only dictionary types. "
                )
            )
            key_filepath = self._credentials
        else:
            key_filepath = self._source_path_reader(self._credentials)
        gbq_client = BigQuery.get_bigquery_client(key_filepath)
        gbq_ref = gbq_client.dataset(self._dataset).table(self._tblname)

        gcs_client = Gcs.get_gcs_client(key_filepath)
        gcs_bucket = gcs_client.bucket(self._bucket)

        ymd_hms = datetime.now().strftime("%Y%m%d%H%M%S%f")
        path = "%s-%s" % ("".join(random.choices(string.ascii_letters, k=8)), ymd_hms)
        prefix = "%s/%s/%s" % (self._dataset, self._tblname, path)

        """
        gsc dir -> gs://{bucket_name}
                       /{dataset_name}/{table_name}
                       /{XXXXXXXX}-{yyyyMMddHHmmssSSS}/*.csv.gz
        """
        if self._filename:
            dest_gcs = "gs://%s/%s/%s*.csv.gz" % (self._bucket, prefix, self._filename)
        else:
            dest_gcs = "gs://%s/%s/*.csv.gz" % (self._bucket, prefix)

        # job config settings
        job_config = bigquery.ExtractJobConfig()
        job_config.compression = bigquery.Compression.GZIP
        job_config.destination_format = bigquery.DestinationFormat.CSV

        # Execute query.
        job = gbq_client.extract_table(
            gbq_ref, dest_gcs, job_config=job_config, location=self._location
        )
        job.result()

        # Download from gcs
        for blob in gcs_client.list_blobs(gcs_bucket, prefix=prefix):
            dest = os.path.join(self._dest_dir, os.path.basename(blob.name))
            blob.download_to_filename(dest)

        # Cleanup temporary files
        for blob in gcs_client.list_blobs(gcs_bucket, prefix=prefix):
            blob.delete()


class GcsDownload(BaseGcs):
    """
    Download from GCS
    """

    def __init__(self):
        super().__init__()
        self._prefix = None
        self._delimiter = None
        self._src_pattern = None
        self._dest_dir = "."

    def prefix(self, prefix):
        self._prefix = prefix

    def delimiter(self, delimiter):
        self._delimiter = delimiter

    def src_pattern(self, src_pattern):
        self._src_pattern = src_pattern

    def dest_dir(self, dest_dir):
        self._dest_dir = dest_dir

    def execute(self, *args):
        super().execute()

        valid = EssentialParameters(self.__class__.__name__, [self._src_pattern])
        valid()

        if isinstance(self._credentials, str):
            self._logger.warning(
                (
                    "DeprecationWarning: "
                    "In the near future, "
                    "the `credentials` will be changed to accept only dictionary types. "
                    "Please see more information "
                    "https://github.com/BrainPad/cliboa/blob/master/docs/modules/gcs_download.md"
                )
            )
            key_filepath = self._credentials
        else:
            key_filepath = self._source_path_reader(self._credentials)
        client = Gcs.get_gcs_client(key_filepath)
        bucket = client.bucket(self._bucket)
        dl_files = []
        for blob in client.list_blobs(
            bucket, prefix=self._prefix, delimiter=self._delimiter
        ):
            r = re.compile(self._src_pattern)
            if not r.fullmatch(blob.name):
                continue
            dl_files.append(blob.name)
            blob.download_to_filename(
                os.path.join(self._dest_dir, os.path.basename(blob.name))
            )

        ObjectStore.put(self._step, dl_files)


class GcsDownloadFileDelete(BaseGcs):
    """
    Delete files downloaded from GCS by using cache
    """

    def __init__(self):
        super().__init__()

    def execute(self, *args):
        dl_files = ObjectStore.get(self._symbol)

        if len(dl_files) > 0:
            self._logger.info("Delete files %s" % dl_files)
            client = self._gcs_client()
            bucket = client.bucket(super().get_step_argument("bucket"))
            for blob in client.list_blobs(
                bucket,
                prefix=super().get_step_argument("prefix"),
                delimiter=super().get_step_argument("delimiter"),
            ):
                for dl_f in dl_files:
                    if dl_f == blob.name:
                        blob.delete()
                        break
        else:
            self._logger.info("No files to delete.")


class FirestoreDocumentDownload(BaseFirestore):
    """
    Download a document from Firestore
    """

    def __init__(self):
        super().__init__()
        self._dest_dir = None

    def dest_dir(self, dest_dir):
        self._dest_dir = dest_dir

    def execute(self, *args):
        super().execute()

        valid = EssentialParameters(
            self.__class__.__name__, [self._collection, self._document, self._dest_dir]
        )
        valid()

        if isinstance(self._credentials, str):
            self._logger.warning(
                (
                    "DeprecationWarning: "
                    "In the near future, "
                    "the `credentials` will be changed to accept only dictionary types. "
                    "Please see more information "
                    "https://github.com/BrainPad/cliboa/blob/master/docs/modules/firestore_document_download.md"  # noqa
                )
            )
            key_filepath = self._credentials
        else:
            key_filepath = self._source_path_reader(self._credentials)
        firestore_client = Firestore.get_firestore_client(key_filepath)
        ref = firestore_client.document(self._collection, self._document)
        doc = ref.get()

        with open(os.path.join(self._dest_dir, doc.id), mode="wt") as f:
            f.write(json.dumps(doc.to_dict()))
