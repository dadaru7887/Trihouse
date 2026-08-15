import 'package:http/http.dart' as http;

http.Client createBrowserHttpClient({required bool withCredentials}) =>
    http.Client();
