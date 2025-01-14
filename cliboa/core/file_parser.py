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
import yaml

from abc import abstractmethod
from cliboa.core.validator import EssentialKeys, ScenarioYamlKey, ScenarioYamlType
from cliboa.util.lisboa_log import LisboaLog


class ScenarioParser(object):
    """
    Base class of scenario file parser
    """

    def __init__(self, pj_scenario_file, cmn_scenario_file):
        self._logger = LisboaLog.get_logger(__name__)
        self._pj_scenario_file = pj_scenario_file
        self._cmn_scenario_file = cmn_scenario_file

    @abstractmethod
    def parse(self):
        """
        Parse scenario file
        """


class YamlScenarioParser(ScenarioParser):
    """
    scenario.yml parser
    """

    def parse(self):
        self._logger.info("Start to parse scenario.yml")

        # Load projet scenario file
        with open(self._pj_scenario_file, "r") as pj_f:
            pj_yaml_dict = yaml.safe_load(pj_f)
            self._valid_scenario_yaml(pj_yaml_dict)
            self._exists_ess_keys(pj_yaml_dict["scenario"])

        # Load common scenario file (if exist)
        cmn_yaml_dict = None
        if os.path.isfile(self._cmn_scenario_file):
            with open(self._cmn_scenario_file, "r") as cmn_f:
                cmn_yaml_dict = yaml.safe_load(cmn_f)
                self._valid_scenario_yaml(cmn_yaml_dict)
                self._exists_ess_keys(cmn_yaml_dict["scenario"])

        if cmn_yaml_dict:
            yaml_list = self._merge_scenario_yaml(
                pj_yaml_dict["scenario"], cmn_yaml_dict["scenario"]
            )
        else:
            yaml_list = pj_yaml_dict.get("scenario")

        self._logger.info("Finish to parse scenario.yml")
        return yaml_list

    def _valid_scenario_yaml(self, yaml_dict):
        """
        validate instance type and essential key in scenario.yml
        """
        valids = [ScenarioYamlKey, ScenarioYamlType]
        for valid in valids:
            valid(yaml_dict)()

    def _merge_scenario_yaml(self, pj_yaml_list, cmn_yaml_list):
        """
        Merge project scenario.yml and common scenario.yml.
        If the same class specification exists,
        scenario.yml of projet is taken priority.
        """
        for pj_yaml_dict in pj_yaml_list:
            # If same class exists, merge arguments
            if pj_yaml_dict.get("parallel"):
                for row in pj_yaml_dict.get("parallel"):
                    self._merge(row, cmn_yaml_list)
            else:
                self._merge(pj_yaml_dict, cmn_yaml_list)

        return pj_yaml_list

    def _merge(self, pj_yaml_dict, cmn_yaml_list):
        cmn_yaml_dict_in_list = [
            d for d in cmn_yaml_list if d.get("class") == pj_yaml_dict.get("class")
        ]
        if not cmn_yaml_dict_in_list:
            return

        pj_cls_attrs = pj_yaml_dict.get("arguments", "")
        cmn_cls_attrs = cmn_yaml_dict_in_list[0].get("arguments")

        # Merge arguments
        if pj_cls_attrs and cmn_cls_attrs:
            pj_cls_attrs = dict(cmn_cls_attrs, **pj_cls_attrs)
        elif not pj_cls_attrs and cmn_cls_attrs:
            pj_cls_attrs = cmn_cls_attrs
        pj_yaml_dict["arguments"] = pj_cls_attrs

    def _exists_ess_keys(self, scenario_yaml_list):
        """
        Check if the essential keys exist in scenario.yml
        """
        valid = EssentialKeys(scenario_yaml_list)
        valid()


class JsonScenarioParser:
    """
    TODO: implement in the future
    """
