import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api_client.dart';
import 'package:rmf_control_ui/trihouse/presentation/shared.dart';

void main() {
  testWidgets('Gateway failure panel hides diagnostics from the operator', (
    tester,
  ) async {
    const failure = FmsApiException(
      kind: FmsApiErrorKind.server,
      operation: 'GET inventory lots',
      diagnosticDetail: 'private SQL and stack trace',
      statusCode: 500,
    );

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(body: GatewayFailurePanel(error: failure)),
      ),
    );

    expect(find.text(failure.safeMessage), findsOneWidget);
    expect(find.textContaining('private SQL'), findsNothing);
    expect(find.textContaining('stack trace'), findsNothing);
  });
}
