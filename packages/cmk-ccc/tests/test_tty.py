#!/usr/bin/env python3
# Copyright (C) 2019 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

import pytest

from cmk.ccc import tty


def test_print_table(capsys: pytest.CaptureFixture[str]) -> None:
    tty.print_table(["foo", "bar"], ["", ""], [["Guildo", "Horn"], ["Dieter Thomas", "Kuhn"]])
    captured = capsys.readouterr()
    assert captured.out == (
        "foo           bar \n------------- ----\nGuildo        Horn\nDieter Thomas Kuhn\n"
    )
    assert captured.err == ""


def test_print_colored_table(capsys: pytest.CaptureFixture[str]) -> None:
    tty.print_table(["foo", "bar"], ["XX", "YY"], [["Angus", "Young"], ["Estas", "Tonne"]])
    captured = capsys.readouterr()
    assert captured.out == ("XXfoo  YY bar  \nXX-----YY -----\nXXAngusYY Young\nXXEstasYY Tonne\n")
    assert captured.err == ""


def test_print_indented_colored_table(capsys: pytest.CaptureFixture[str]) -> None:
    tty.print_table(
        ["foo", "bar"], ["XX", "YY"], [["Dieter", "Bohlen"], ["Thomas", "Anders"]], indent="===="
    )
    captured = capsys.readouterr()
    assert captured.out == (
        "====XXfoo   YY bar   \n"
        "====XX------YY ------\n"
        "====XXDieterYY Bohlen\n"
        "====XXThomasYY Anders\n"
    )
    assert captured.err == ""
