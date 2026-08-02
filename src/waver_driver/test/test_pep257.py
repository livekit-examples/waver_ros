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

from ament_pep257.main import main
import pytest


@pytest.mark.linter
@pytest.mark.pep257
def test_pep257():
    # D212 and D213 are mutually exclusive: one demands the docstring summary on
    # the opening-quotes line, the other on the line below it. The ament
    # convention ignores D212 and so enforces D213; this package consistently
    # uses the D212 style, so ignore D213 as well and accept either. Everything
    # else in the ament convention stays enforced -- --add-ignore is additive.
    rc = main(argv=['.', 'test', '--add-ignore', 'D213'])
    assert rc == 0, 'Found code style errors / warnings'
