import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:rmf_control_ui/trihouse/api/fms_api_client.dart';

void main() {
  test('same-origin session cookies are the default browser policy', () async {
    final configuration = GatewayClientConfiguration.resolve(
      pageUri: Uri.parse('https://control.example/app/index.html'),
    );
    bool? capturedWithCredentials;
    final client = FmsApiClient.forBrowser(
      configuration: configuration,
      browserHttpClientFactory: ({required bool withCredentials}) {
        capturedWithCredentials = withCredentials;
        return MockClient(
          (_) async => http.Response(jsonEncode(<Object?>[]), 200),
        );
      },
    );

    await client.listInventory();

    expect(configuration.baseUri, Uri.parse('https://control.example/'));
    expect(
      configuration.credentialMode,
      GatewayCredentialMode.sameOriginSessionCookie,
    );
    expect(capturedWithCredentials, isFalse);
  });

  test('cross-origin cookies require explicit credentialed configuration', () {
    expect(
      () => GatewayClientConfiguration.resolve(
        pageUri: Uri.parse('https://control.example/app/'),
        configuredBaseUrl: 'https://gateway.example',
      ),
      throwsA(
        isA<FmsApiException>().having(
          (error) => error.kind,
          'kind',
          FmsApiErrorKind.configuration,
        ),
      ),
    );
  });

  test(
    'explicit cross-origin mode configures a credentialed BrowserClient',
    () {
      final configuration = GatewayClientConfiguration.resolve(
        pageUri: Uri.parse('https://control.example/app/'),
        configuredBaseUrl: 'https://gateway.example',
        allowCredentialedCrossOrigin: true,
      );
      bool? capturedWithCredentials;

      FmsApiClient.forBrowser(
        configuration: configuration,
        browserHttpClientFactory: ({required bool withCredentials}) {
          capturedWithCredentials = withCredentials;
          return MockClient((_) async => http.Response('[]', 200));
        },
      );

      expect(
        configuration.credentialMode,
        GatewayCredentialMode.credentialedCrossOriginSessionCookie,
      );
      expect(capturedWithCredentials, isTrue);
    },
  );

  test('base URI rejects non-http schemes and embedded credentials', () {
    for (final configured in [
      'file:///tmp/gateway',
      'ws://gateway.example',
      'https://worker:secret@gateway.example',
    ]) {
      expect(
        () => GatewayClientConfiguration.resolve(
          pageUri: Uri.parse('https://control.example/'),
          configuredBaseUrl: configured,
          allowCredentialedCrossOrigin: true,
        ),
        throwsA(
          isA<FmsApiException>().having(
            (error) => error.kind,
            'kind',
            FmsApiErrorKind.configuration,
          ),
        ),
        reason: configured,
      );
    }
  });

  test('credentialed cross-origin session cookies require HTTPS', () {
    expect(
      () => GatewayClientConfiguration.resolve(
        pageUri: Uri.parse('http://control.example/'),
        configuredBaseUrl: 'http://gateway.example',
        allowCredentialedCrossOrigin: true,
      ),
      throwsA(
        isA<FmsApiException>().having(
          (error) => error.kind,
          'kind',
          FmsApiErrorKind.configuration,
        ),
      ),
    );
  });
}
