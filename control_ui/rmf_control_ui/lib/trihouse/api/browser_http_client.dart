import 'package:http/http.dart' as http;

import 'browser_http_client_stub.dart'
    if (dart.library.js_interop) 'browser_http_client_web.dart'
    as implementation;

http.Client createBrowserHttpClient({required bool withCredentials}) =>
    implementation.createBrowserHttpClient(withCredentials: withCredentials);
