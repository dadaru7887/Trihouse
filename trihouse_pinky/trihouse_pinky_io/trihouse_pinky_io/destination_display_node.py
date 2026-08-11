"""FMS 목적지 코드를 LCD로 출력하는 node. Pinky 감정 애니메이션 대신 실행한다."""

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .destination_display import destination_label


class DestinationDisplay(Node):
    def __init__(self) -> None:
        super().__init__('destination_display')
        self.declare_parameter('font_path', '')
        self.font_path = self.get_parameter('font_path').value
        self.lcd = None
        self.create_subscription(String, '/trihouse/display/destination_code', self._show, 10)

    def _show(self, message: String) -> None:
        label = destination_label(message.data)
        if label is None:
            if self.lcd is not None: self.lcd.clear()
            return
        if not self.font_path:
            self.get_logger().error('font_path is required to render Korean destination text')
            return
        try:
            from PIL import Image, ImageDraw, ImageFont
            from pinky_emotion.pinky_lcd import LCD
            if self.lcd is None: self.lcd = LCD()
            image = Image.new('RGB', (240, 320), 'black'); draw = ImageDraw.Draw(image)
            font = ImageFont.truetype(self.font_path, 32)
            box = draw.multiline_textbbox((0, 0), label, font=font, align='center', spacing=8)
            draw.multiline_text(((240-(box[2]-box[0]))/2, (320-(box[3]-box[1]))/2), label, font=font, fill='white', align='center', spacing=8)
            self.lcd.img_show(image)
        except Exception as error:
            self.get_logger().error(f'LCD destination display failed: {error}')


def main() -> None:
    rclpy.init(); node = DestinationDisplay()
    try: rclpy.spin(node)
    finally:
        if node.lcd is not None: node.lcd.clear(); node.lcd.close()
        node.destroy_node(); rclpy.shutdown()
