"""還原點是不是真的建起來了。

**2026-08-10 發現的洞。** 按下「全部開始」時 `--stage-only` 會去比對指紋，指紋沒變
就跳過不停機 —— 但它比的是**每日備份的上傳戳記**，而那個戳記的意思是「這個狀態已經
上傳到 restic 了」，不是「本機現在有一份可以換回去的複本」。

每日備份上傳成功之後會把本機暫存 `rm -rf` 掉。所以常態長這樣：

    04:00  備份 → 上傳成功 → 寫戳記 → 刪掉本機複本
    10:00  放 PDF、按全部開始 → 指紋沒變（中間沒抽過東西）→ 跳過
           ⇒ 本機還原點從來沒被建出來過

實測（2026-08-10 20:40，dker）：戳記與現在的指紋逐字相同，
而 `/data/lightrag-restorepoint` 不存在。這個功能等於沒有在運作。

修法：兩種模式問的是不同的問題，就該看不同的戳記。
`--stage-only` 有自己的戳記，而且**跳過之前還要確認那個目錄真的還在**。

這幾支是真的把腳本跑起來（docker 與 sudo 換成假的），因為這是控制流程的錯 ——
讀原始碼比對字串抓不到它。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "backup-cold.sh"

FINGERPRINT = "257:3491:43706:63170:2026-08-1003:08:55.390794"

# 假 docker：記下每一次呼叫（用來確認有沒有停容器），並在被問指紋時回答。
_DOCKER = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case "$*" in
  *psql*) cat >/dev/null; printf '%s\\n' "$FAKE_FP" ;;
esac
exit 0
"""

# 假 sudo：直接執行，不提權。rm/mkdir/rsync/find 都在 tmp 底下真的跑。
_SUDO = """#!/usr/bin/env bash
exec "$@"
"""


class Sandbox:
    """一份可以真的跑 backup-cold.sh 的假環境。"""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        repo = tmp_path / "repo"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "backup-cold.sh").symlink_to(SCRIPT)

        self.db_root = tmp_path / "data" / "lightrag"
        (self.db_root / "postgres").mkdir(parents=True)
        for i in range(12):  # 腳本要求 postgres 底下至少 10 個檔才算像資料目錄
            (self.db_root / "postgres" / f"{i}.dat").write_text("x", encoding="utf-8")
        (self.db_root / "models" / "hub").mkdir(parents=True)
        (self.db_root / "models" / "hub" / "big.bin").write_text("w", encoding="utf-8")
        (repo / ".env").write_text(f"LIGHTRAG_DB_ROOT={self.db_root}\n", encoding="utf-8")

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in (("docker", _DOCKER), ("sudo", _SUDO)):
            path = bin_dir / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

        self.script = repo / "scripts" / "backup-cold.sh"
        self.docker_log = tmp_path / "docker.log"
        self.stage = tmp_path / "coldstage"
        self.restore_point = tmp_path / "restorepoint"
        self.upload_stamp = self.db_root / ".backup-cold.stamp"
        self.restore_stamp = Path(f"{self.restore_point}.stamp")
        self._bin = bin_dir

    def run(self, *args: str, fingerprint: str = FINGERPRINT) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        env.update(
            PATH=f"{self._bin}:{env['PATH']}",
            DOCKER_LOG=str(self.docker_log),
            FAKE_FP=fingerprint,
            BACKUP_STAGE_DIR=str(self.stage),
            BACKUP_RESTOREPOINT_DIR=str(self.restore_point),
            BACKUP_LOCK=str(self.tmp / "lock"),
        )
        return subprocess.run(
            ["bash", str(self.script), *args],
            capture_output=True, text=True, env=env, timeout=120, check=False,
        )

    def stopped_containers(self) -> list[str]:
        if not self.docker_log.exists():
            return []
        return [ln for ln in self.docker_log.read_text(encoding="utf-8").splitlines()
                if ln.startswith("stop ")]


def test_a_restore_point_is_built_even_when_the_upload_stamp_matches(tmp_path: Path) -> None:
    """**這一條就是那個洞。**

    每日備份剛跑完（戳記＝現在的指紋、本機複本已刪），這時按下「全部開始」——
    還原點必須真的被建出來。拿「已經上傳過了」當作「本機有複本」是錯的：
    上傳到 Google Drive 的那份，還原方式是從 restic 拉回來，**而那條路沒有人走過**。
    """
    box = Sandbox(tmp_path)
    box.upload_stamp.write_text(FINGERPRINT + "\n", encoding="utf-8")

    result = box.run("--stage-only")

    assert result.returncode == 0, result.stdout + result.stderr
    assert box.restore_point.is_dir(), f"還原點沒建出來：\n{result.stdout}"
    assert (box.restore_point / "postgres" / "0.dat").is_file(), "複本裡沒有資料"


def test_the_restore_point_still_excludes_the_model_weights(tmp_path: Path) -> None:
    """控制組：修完之後 `--stage-only` 走的還是排除 models 的那條複製。

    models/ 是可重下的權重快取，抄它只會把停機窗拉長。
    """
    box = Sandbox(tmp_path)
    box.run("--stage-only")
    assert box.restore_point.is_dir()
    assert not (box.restore_point / "models").exists(), "models/ 被抄進還原點了"


def test_pressing_start_twice_does_not_stop_the_containers_again(tmp_path: Path) -> None:
    """**跳過本身是對的，別把它修掉。**

    停機窗實測 77 秒，中間查詢打不到。同一個指紋已經有還原點了還再停一次，
    那 77 秒買不到任何東西。
    """
    box = Sandbox(tmp_path)
    first = box.run("--stage-only")
    assert box.restore_point.is_dir(), first.stdout
    (box.restore_point / "SENTINEL").write_text("1", encoding="utf-8")
    box.docker_log.unlink(missing_ok=True)

    second = box.run("--stage-only")

    assert second.returncode == 0, second.stdout + second.stderr
    assert box.stopped_containers() == [], f"第二次又停了容器：{box.stopped_containers()}"
    assert (box.restore_point / "SENTINEL").exists(), "白重建了一次"


def test_a_deleted_restore_point_is_rebuilt(tmp_path: Path) -> None:
    """戳記說有、目錄卻不見了 —— 要重建，不能相信戳記。

    戳記是那份複本的收據，不是複本。
    """
    box = Sandbox(tmp_path)
    box.run("--stage-only")
    assert box.restore_stamp.exists(), "還原點沒有自己的戳記"
    subprocess.run(["rm", "-rf", str(box.restore_point)], check=True)

    result = box.run("--stage-only")

    assert result.returncode == 0, result.stdout + result.stderr
    assert box.restore_point.is_dir(), f"目錄被刪了卻沒重建：\n{result.stdout}"


def test_the_restore_point_never_writes_the_upload_stamp(tmp_path: Path) -> None:
    """**最重要的控制組。**

    上傳戳記的意思是「這個狀態已經在 restic 裡」。還原點沒有上傳，寫了它會讓
    當晚 04:00 那次誤以為已經備過而跳過 —— 異地備份就這樣安靜地停掉了。
    """
    box = Sandbox(tmp_path)
    result = box.run("--stage-only")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not box.upload_stamp.exists(), "還原點寫了上傳戳記，當晚的異地備份會被跳過"


def test_the_daily_backup_still_skips_on_an_unchanged_fingerprint(tmp_path: Path) -> None:
    """控制組：每日那條路的跳過邏輯不能被我改壞。

    它的暫存區**本來就會在上傳成功後被刪掉**，所以它的跳過不該去看目錄在不在。
    """
    box = Sandbox(tmp_path)
    box.upload_stamp.write_text(FINGERPRINT + "\n", encoding="utf-8")

    result = box.run()

    assert result.returncode == 0, result.stdout + result.stderr
    assert "跳過" in result.stdout, result.stdout
    assert box.stopped_containers() == [], "指紋沒變卻停了容器"
