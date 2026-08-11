#
# Copyright 2026 LiveKit
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

cmake_minimum_required(VERSION 3.8)
project(waver_localization)

find_package(ament_cmake_auto REQUIRED)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # D212 and D213 are mutually exclusive: one wants the docstring summary on the
  # opening-quotes line, the other on the line below. The ament convention
  # ignores D212 and so enforces D213, but this repo uses the D212 style, so run
  # pep257 explicitly with D213 ignored instead of with ament_lint_auto's
  # defaults. Same decision as waver_driver/test/test_pep257.py.
  list(APPEND AMENT_LINT_AUTO_EXCLUDE ament_cmake_pep257)
  ament_lint_auto_find_test_dependencies()
  ament_pep257(--add-ignore D213)
endif()

install(PROGRAMS
  scripts/rf2o_covariance_relay.py
  DESTINATION lib/${PROJECT_NAME})

ament_auto_package(USE_SCOPED_HEADER_INSTALL_DIR INSTALL_TO_SHARE config launch)
