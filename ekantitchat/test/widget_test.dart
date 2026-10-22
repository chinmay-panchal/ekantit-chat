import 'package:flutter_test/flutter_test.dart';
import 'package:ekantitchat/main.dart';

void main() {
  testWidgets('EkantitChat smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const EkantitChatApp());
    expect(find.text('Ekantit Chat'), findsOneWidget);
  });
}
