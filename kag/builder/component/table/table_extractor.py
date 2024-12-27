# -*- coding: utf-8 -*-
# Copyright 2023 OpenSPG Authors
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except
# in compliance with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License
# is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
# or implied.

import json
import logging
import os
import markdown
from bs4 import BeautifulSoup, Tag
from typing import List, Set, Dict


from kag.interface.builder import ExtractorABC
from kag.common.base.prompt_op import PromptOp
from kag.builder.model.chunk import Chunk
from knext.common.base.runnable import Input, Output

import os
import logging
import json
import pandas as pd
from io import StringIO

from kag.builder.model.chunk import Chunk, ChunkTypeEnum
from kag.builder.component.splitter.base_table_splitter import BaseTableSplitter
from kag.builder.component.extractor.kag_extractor import KAGExtractor
from kag.builder.component.table.table_cell import TableCell, TableInfo
from knext.common.base.runnable import Input, Output


from typing import List

import logging
import os
from typing import List


from kag.interface.builder import ExtractorABC
from kag.builder.model.sub_graph import SubGraph, Node, Edge

logger = logging.getLogger(__name__)


logger = logging.getLogger(__name__)


class TableExtractor(ExtractorABC, BaseTableSplitter):
    """
    table extractor
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.llm = self._init_llm()
        self.prompt_config = self.config.get("prompt", {})
        self.biz_scene = self.prompt_config.get("biz_scene") or os.getenv(
            "KAG_PROMPT_BIZ_SCENE", "default"
        )
        self.language = self.prompt_config.get("language") or os.getenv(
            "KAG_PROMPT_LANGUAGE", "zh"
        )
        self.table_keywords_prompt = PromptOp.load("table", "table_keywords")(
            language=self.language, project_id=self.project_id
        )
        self.table_reformat = PromptOp.load("table", "table_reformat")(
            language=self.language, project_id=self.project_id
        )
        self.kag_extractor = KAGExtractor(**kwargs)

    @property
    def input_types(self) -> Input:
        return Chunk

    @property
    def output_types(self) -> Output:
        return SubGraph

    def invoke(self, input: Input, **kwargs) -> List[Output]:
        """
        invoke
        """
        input_table: Chunk = input
        table_type = input_table.kwargs["table_type"]
        if table_type in ["指标型表格", "Metric_Based_Table"]:
            return self._extract_metric_table(input_table)
        elif table_type in ["简单表格", "Simple_Table"]:
            return self._extract_simple_table(input_table)
        else:
            return self._extract_other_table(input_table)

    def _extract_metric_table(self, input_table: Chunk):
        table_info = input_table.kwargs["table_info"]
        header = table_info["header"]
        index_col = table_info["index_col"]
        table_df, header, index_col = self._std_table(
            input_table=input_table,
            header=header,
            index_col=index_col,
            use_llm_reformat=True,
        )
        table_name = input_table.kwargs["table_name"]
        cell_value_desc = None
        scale = table_info.get("scale", None)
        units = table_info.get("units", None)
        if scale is not None:
            cell_value_desc = str(scale)
        if units is not None and isinstance(units, str):
            cell_value_desc += "," + units
        if cell_value_desc is not None:
            cell_value_desc = "(" + cell_value_desc + ")"

        spo_list = self._get_table_sub_item_info(data=table_df)
        table_cell_info: TableInfo = self._generate_table_cell_info(
            data=table_df,
            header=header,
            table_name=table_name,
            cell_value_desc=cell_value_desc,
        )
        table_cell_info.sacle = table_info.get("scale", None)
        table_cell_info.unit = table_info.get("units", None)
        table_cell_info.context_keywords = input_table.kwargs["keywords"]
        keyword_set = set()
        keyword_set.add(table_name)
        for table_cell in table_cell_info.cell_dict.values():
            table_cell: TableCell = table_cell
            keyword_set.update(list(table_cell.row_keywords.keys()))
        keywords_and_colloquial_expression = self._extract_keyword_from_table_header(
            keyword_set=keyword_set, table_name=table_name
        )
        for k, v in keywords_and_colloquial_expression.items():
            if k == table_name:
                table_cell_info.table_name_colloquial = v
                continue
            for table_cell in table_cell_info.cell_dict.values():
                if k in table_cell.row_keywords:
                    table_cell.row_keywords[k] = v
        return self.get_subgraph(
            input_table,
            table_df,
            table_cell_info,
            spo_list,
        )

    def _extract_keyword_from_table_header(self, keyword_set: Set, table_name: str):
        context = table_name
        keyword_list = list(keyword_set)
        keyword_list.sort()
        input_dict = {"key_list": keyword_list, "context": context}
        keywords_and_colloquial_expression = self.llm.invoke(
            {
                "input": json.dumps(input_dict, ensure_ascii=False, sort_keys=True),
            },
            self.table_keywords_prompt,
            with_json_parse=True,
            with_except=True,
        )
        return keywords_and_colloquial_expression

    def _extract_simple_table(self, input_table: Chunk):
        rst = []
        if "table_info" in input_table.kwargs:
            table_info = input_table.kwargs["table_info"]
        else:
            table_info = {}
        if "header" in table_info and "index_col" in table_info:
            header = table_info["header"]
            index_col = table_info["index_col"]
            self._std_table(input_table=input_table, header=header, index_col=index_col)
        # 调用ner进行实体识别
        table_chunks = self.split_table(input_table, 500)
        for c in table_chunks:
            subgraph_lsit = self.kag_extractor.invoke(input=c)
            rst.extend(subgraph_lsit)
        return rst

    def _extract_other_table(self, input_table: Chunk):
        return self._extract_simple_table(input_table=input_table)

    def _std_table(
        self,
        input_table: Chunk,
        header: List,
        index_col: List,
        use_llm_reformat: bool = False,
    ):
        """
        按照表格新识别的表头，生成markdown文本
        """
        if use_llm_reformat:
            try:
                return self._std_table2(input_table=input_table)
            except:
                pass
        if "html" in input_table.kwargs:
            html = input_table.kwargs["html"]
            try:
                if len(header) <= 0:
                    header = None
                if not index_col or len(index_col) <= 0:
                    index_col = None
                table_df = pd.read_html(
                    StringIO(html),
                    header=header,
                    index_col=index_col,
                )[0]
            except IndexError:
                logging.exception("read html errro")
            table_df = table_df.fillna("")
            table_df = table_df.astype(str)
            input_table.content = table_df.to_markdown()
            del input_table.kwargs["html"]
            input_table.kwargs["content_type"] = "markdown"
            input_table.kwargs["csv"] = table_df.to_csv()
            return table_df, header, index_col

    def _std_table2(self, input_table: Chunk):
        """
        转换表格
        使用大模型转换
        """
        input_str = input_table.content
        new_markdown = self.llm.invoke(
            {"input": input_str}, self.table_reformat, with_except=True
        )
        html_content = markdown.markdown(
            new_markdown, extensions=["markdown.extensions.tables"]
        )
        table_df = pd.read_html(StringIO(html_content), header=[0], index_col=[0])[0]
        table_df = table_df.fillna("")
        table_df = table_df.astype(str)
        input_table.content = table_df.to_markdown()
        del input_table.kwargs["html"]
        input_table.kwargs["content_type"] = "markdown"
        input_table.kwargs["csv"] = table_df.to_csv()
        return table_df, [0], [0]

    def get_subgraph(
        self,
        input_table: Chunk,
        table_df: pd.DataFrame,
        table_cell_info: TableInfo,
        subitem_spo_list: List,
    ):
        nodes = []
        edges = []

        all_keywords_dict = {}

        table_id = input_table.id

        # Table node
        table_desc = input_table.kwargs["context"]
        table_name = input_table.kwargs["table_name"]
        table_node = Node(
            _id=table_id,
            name=table_name,
            label="Table",
            properties={
                "content": input_table.content,
                "csv": table_df.to_csv(),
                "desc": table_desc,
            },
        )
        nodes.append(table_node)

        # table name
        table_name_node = Node(
            _id="tn_" + table_id,
            name=table_name,
            label="MetricConstraint",
            properties={
                "type": "table_name",
            },
        )
        nodes.append(table_name_node)
        edge = Edge(
            _id="t2tn_" + table_id,
            from_node=table_name_node,
            to_node=table_node,
            label="dimension",
            properties={},
        )
        edges.append(edge)

        # all cell node
        for k, cell in table_cell_info.cell_dict.items():
            table_cell: TableCell = cell
            cell_id = f"{table_id}_{k}"
            # cell node
            metric = Node(
                _id=cell_id,
                name=table_cell.desc,
                label="TableMetric",
                properties={
                    "value": table_cell.value,
                    "scale": table_cell_info.sacle,
                    "unit": table_cell_info.unit,
                },
            )
            nodes.append(metric)

            # cell to table
            edge = Edge(
                _id="c2t_" + cell_id,
                from_node=metric,
                to_node=table_node,
                label="source",
                properties={},
            )
            edges.append(edge)

            # all table global keywords
            global_keywords = input_table.kwargs.get("keywords", [])
            for gk in global_keywords:
                global_keyword: str = gk
                keyword_id = f"global_keywords_{global_keyword}"
                if keyword_id in all_keywords_dict:
                    continue
                keyword_node = Node(
                    _id=keyword_id,
                    name=global_keyword,
                    label="MetricConstraint",
                    properties={"type": "global"},
                )
                all_keywords_dict[keyword_id] = keyword_node
                nodes.append(keyword_node)

                # keywrod to metric
                edge = Edge(
                    _id="gk2c_" + keyword_id,
                    from_node=keyword_node,
                    to_node=metric,
                    label="dimension",
                    properties={},
                )
                edges.append(edge)

            # all row_keywords
            for rk, rv in table_cell.row_keywords.items():
                row_keyword: str = rk
                keyword_id = f"{table_name}_{row_keyword}"
                if keyword_id in all_keywords_dict:
                    continue
                keyword_node = Node(
                    _id=keyword_id,
                    name=row_keyword,
                    label="MetricConstraint",
                    properties={"type": "row"},
                )
                all_keywords_dict[keyword_id] = keyword_node
                nodes.append(keyword_node)

                # keywrod to metric
                edge = Edge(
                    _id="k2c_" + keyword_id,
                    from_node=keyword_node,
                    to_node=metric,
                    label="dimension",
                    properties={},
                )
                edges.append(edge)

                # all splited keywords
                for sk, sv in rv.items():
                    splited_keyword: str = sk
                    s_keyword_id = f"{table_name}_{splited_keyword}"
                    if s_keyword_id in all_keywords_dict:
                        splited_keyword_node = all_keywords_dict[s_keyword_id]
                        c_nodes, c_edges = self._get_colloquial_nodes_and_edges(
                            colloquial_list=sv,
                            table_name=table_name,
                            all_keywords_dict=all_keywords_dict,
                            splited_keyword_node=splited_keyword_node,
                        )
                        nodes.extend(c_nodes)
                        edges.extend(c_edges)
                        continue
                    splited_keyword_node = Node(
                        _id=s_keyword_id,
                        name=splited_keyword,
                        label="MetricConstraint",
                        properties={"type": "splited"},
                    )
                    all_keywords_dict[s_keyword_id] = splited_keyword_node
                    nodes.append(splited_keyword_node)

                    # keyword to row_keyword
                    edge = Edge(
                        _id="k2rk_" + s_keyword_id,
                        from_node=splited_keyword_node,
                        to_node=keyword_node,
                        label="parent",
                        properties={},
                    )
                    edges.append(edge)

                    c_nodes, c_edges = self._get_colloquial_nodes_and_edges(
                        colloquial_list=sv,
                        table_name=table_name,
                        all_keywords_dict=all_keywords_dict,
                        splited_keyword_node=splited_keyword_node,
                    )
                    nodes.extend(c_nodes)
                    edges.extend(c_edges)
        # subitem edge
        for spo in subitem_spo_list:
            s_id = f"{table_name}_{spo[0]}"
            o_id = f"{table_name}_{spo[2]}"
            if s_id in all_keywords_dict and o_id in all_keywords_dict:
                edge = Edge(
                    _id="subitem_" + s_id + "_" + o_id,
                    from_node=all_keywords_dict[s_id],
                    to_node=all_keywords_dict[o_id],
                    label="subitem",
                    properties={},
                )
                edges.append(edge)

        subgraph = SubGraph(nodes=nodes, edges=edges)
        return [subgraph]

    def _get_colloquial_nodes_and_edges(
        self,
        colloquial_list: List,
        table_name: str,
        all_keywords_dict: Dict,
        splited_keyword_node: Node,
    ):
        nodes = []
        edges = []
        if len(colloquial_list) > 2:
            colloquial_list = colloquial_list[:2]
        for ck in colloquial_list:
            colloquial_keyword: str = ck
            c_keyword_id = f"{table_name}_{colloquial_keyword}"
            if c_keyword_id in all_keywords_dict:
                continue
            c_keyword_node = Node(
                _id=c_keyword_id,
                name=colloquial_keyword,
                label="MetricConstraint",
                properties={"type": "colloquial"},
            )
            all_keywords_dict[c_keyword_id] = c_keyword_node
            nodes.append(c_keyword_node)

            # keyword to row_keyword
            edge = Edge(
                _id="k2rk2c_" + c_keyword_id,
                from_node=c_keyword_node,
                to_node=splited_keyword_node,
                label="colloquial",
                properties={},
            )
            edges.append(edge)
        return nodes, edges

    def _get_table_sub_item_info(
        self,
        data: pd.DataFrame,
    ):
        spo_list = []
        for i in range(data.shape[0]):
            index_column = str(data.index[i])
            if not index_column.strip().startswith("-"):
                continue
            level = self._count_leading_hyphens(index_column)
            for j in reversed(range(0, i)):
                parent_name = str(data.index[j])
                p_level = self._count_leading_hyphens(parent_name)
                if p_level + 1 == level:
                    spo_list.append((parent_name, "包含", index_column))
                    break
        return spo_list

    def _count_leading_hyphens(self, s):
        count = 0
        s = s.strip()
        for char in s:
            if char == "-":
                count += 1
            else:
                break
        return count

    def _generate_table_cell_info(
        self,
        data: pd.DataFrame,
        header,
        table_name,
        cell_value_desc,
    ):
        table_info = TableInfo(table_name=table_name)
        sub_item_dict = {}
        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                value = data.iloc[i, j]
                if (
                    str(value).startswith("Unnamed")
                    or str(value) == ""
                    or str(value) == "-"
                    or str(value) == "\u2014"
                ):
                    continue
                x_index = i + len(header)
                y_index = j + 1
                cell_id = f"{x_index}-{y_index}"
                row_keywords = {}
                describe = ""
                now_index_str = None
                if pd.isnull(data.index[i]):
                    describe += "total"
                    row_keywords["total"] = {}
                else:
                    now_index_str = f"{data.index[i]}"
                    describe += now_index_str
                    row_keywords[now_index_str] = {}
                temp_i = i - 1
                while temp_i >= 0:
                    if (data.iloc[temp_i] == "").all():
                        parent_str = f"{data.index[temp_i]}"
                        parent_str = parent_str.strip(":").strip("：")
                        describe += f" in {parent_str}"
                        row_keywords[parent_str] = {}
                        if now_index_str is not None:
                            sub_item_set = sub_item_dict.get(parent_str, set())
                            sub_item_set.add(now_index_str)
                            sub_item_dict[parent_str] = sub_item_set
                        break
                    temp_i -= 1

                describe += " of"
                if len(header) == 0:
                    pass
                elif len(header) == 1:
                    header_str = self._handle_unnamed_single_topheader(data.columns, j)
                    describe += f" {header_str}"
                    row_keywords[header_str] = {}
                else:
                    header_str = self._handle_unnamed_multi_topheader(data.columns, j)
                    describe += f" {header_str}"
                    row_keywords[header_str] = {}
                    prev = self._handle_unnamed_multi_topheader(data.columns, j)
                    for temp_j in header[1:]:
                        if (
                            data.columns[j][temp_j].startswith("Unnamed")
                            or data.columns[j][temp_j] == ""
                        ):
                            continue
                        if data.columns[j][temp_j] == prev:
                            continue
                        describe += f" {data.columns[j][temp_j]}"
                        row_keywords[f"{data.columns[j][temp_j]}"] = {}
                        prev = data.columns[j][temp_j]
                describe += f" is {data.iloc[i, j]}{cell_value_desc}"
                describe = f"[{table_name}]cell[{cell_id}] shows " + describe
                table_cell = TableCell(desc=describe, row_keywords=row_keywords)
                table_cell.value = data.iloc[i, j]
                table_info.cell_dict[cell_id] = table_cell
        table_info.sub_item_dict = sub_item_dict
        return table_info

    def _handle_unnamed_single_topheader(self, columns, j):
        tmp = j
        while tmp < len(columns) and (
            columns[tmp].startswith("Unnamed") or columns[tmp] == ""
        ):
            tmp += 1
        if tmp < len(columns):
            return columns[tmp]

        tmp = j
        while tmp >= 0 and (columns[tmp].startswith("Unnamed") or columns[tmp] == ""):
            tmp -= 1
        if tmp < 0:
            return f"data {j}"
        else:
            return columns[tmp]

    def _handle_unnamed_multi_topheader(self, columns, j):
        tmp = j
        while tmp < len(columns) and (
            columns[tmp][0].startswith("Unnamed") or columns[tmp][0] == ""
        ):
            tmp += 1
        if tmp < len(columns):
            return columns[tmp][0]

        tmp = j
        while tmp >= 0 and (
            columns[tmp][0].startswith("Unnamed") or columns[tmp][0] == ""
        ):
            tmp -= 1
        if tmp < 0:
            return f"data {j}"
        else:
            return columns[tmp][0]
