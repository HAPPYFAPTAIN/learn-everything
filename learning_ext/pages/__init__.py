"""learning_ext 的 Gradio Tab 页面集合。"""

from learning_ext.pages.coach import CoachPage
from learning_ext.pages.dashboard import DashboardPage
from learning_ext.pages.path_generator import PathGeneratorPage
from learning_ext.pages.quick_setup import QuickSetupPage
from learning_ext.pages.quiz import QuizPage
from learning_ext.pages.review import ReviewPage
from learning_ext.pages.study_workbench import StudyWorkbenchPage

__all__ = [
    "QuickSetupPage",
    "PathGeneratorPage",
    "StudyWorkbenchPage",
    "ReviewPage",
    "QuizPage",
    "DashboardPage",
    "CoachPage",
]
