import os

import pytest
from learning_ext.practice import auto_setup


def test_invalid_command_is_failure():
    outcome = {}
    output = ''.join(auto_setup.run_all_commands([{}, None], outcome=outcome))
    assert outcome == {'total': 2, 'success': 0, 'failed': 2}
    assert '环境配置完成！' not in output


def test_partial_failure_is_not_success(monkeypatch):
    monkeypatch.setattr(auto_setup, 'run_command_streaming', lambda cmd: iter(['[退出码 0 ✓]\n'] if cmd == 'ok' else ['[退出码 1 ⚠️ 可能失败]\n']))
    outcome = {}
    output = ''.join(auto_setup.run_all_commands([{'cmd':'ok'}, {'cmd':'bad'}], outcome=outcome))
    assert outcome == {'total': 2, 'success': 1, 'failed': 1}
    assert '部分命令失败' in output


@pytest.mark.skipif(os.name != 'nt', reason='Windows process execution')
@pytest.mark.parametrize('command,success', [("Write-Output 'setup-test-ok'",True), ("Write-Error 'expected-setup-test-error'",False), ('exit 7',False)])
def test_real_powershell_exit_status(command, success):
    output = list(auto_setup.run_command_streaming(command))
    assert bool('退出码 0' in output[-1]) is success
