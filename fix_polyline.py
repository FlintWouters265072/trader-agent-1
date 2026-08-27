import re

with open("dashboard.py", "r") as f:
    content = f.read()

old_str = r"""      <polyline points="{polyline_points}" fill="none" stroke="{line_color}" stroke-width="2" \
stroke-linejoin="round" stroke-linecap="round" />"""

new_str = """      <defs>
        <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="{line_color}" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="{line_color}" stop-opacity="0.0"/>
        </linearGradient>
      </defs>
      <polygon points="{polyline_points} {end_x:.1f},{zero_y:.1f} {pad:.1f},{zero_y:.1f}" fill="url(#chartGrad)" />
      <polyline points="{polyline_points}" fill="none" stroke="{line_color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />"""

content = content.replace(old_str, new_str)

with open("dashboard.py", "w") as f:
    f.write(content)
