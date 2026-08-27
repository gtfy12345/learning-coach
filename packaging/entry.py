"""LearningCoach.app 打包入口：仅冻结场景使用，开发时走 python -m。"""

import sys

from learning_coach.desktop import run_desktop

if __name__ == "__main__":
    sys.exit(run_desktop(sys.argv[1:]))
