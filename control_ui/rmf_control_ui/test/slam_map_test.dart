import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:rmf_control_ui/slam_map.dart';

void main() {
  group('map_saver YAML parser', () {
    test('parses the map header and strips the image path', () {
      const yaml = '''
image: /maps/my_map.pgm
mode: trinary
resolution: 0.05
origin: [-1.24, -3.87, 0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.25
''';

      final header = parseSlamMapYaml(yaml);

      expect(header.imageName, 'my_map.pgm');
      expect(header.resolution, .05);
      expect(header.originX, -1.24);
      expect(header.originY, -3.87);
      expect(header.originYaw, 0);
      expect(header.negate, isFalse);
      expect(header.freeThreshold, .25);
    });

    test('accepts comments, whitespace, and scientific notation', () {
      final header = parseSlamMapYaml(
        '# map\n\nimage: a.pgm\n  resolution: 5e-2  \n'
        'origin: [-1.2e1, 3.4e-1, 0.75]\n',
      );
      expect(header.resolution, .05);
      expect(header.originX, -12);
      expect(header.originY, .34);
      expect(header.originYaw, .75);
    });

    test('rejects missing or non-positive required values', () {
      expect(
        () => parseSlamMapYaml('image: a.pgm\norigin: [0, 0, 0]\n'),
        throwsA(isA<SlamMapParseError>()),
      );
      expect(
        () => parseSlamMapYaml(
          'image: a.pgm\nresolution: 0\norigin: [0, 0, 0]\n',
        ),
        throwsA(isA<SlamMapParseError>()),
      );
      expect(
        () => parseSlamMapYaml('image: a.pgm\nresolution: 0.05\n'),
        throwsA(isA<SlamMapParseError>()),
      );
    });
  });

  group('PGM parser', () {
    test('parses binary P5 and ASCII P2 cells', () {
      final binary = parsePgm(
        Uint8List.fromList([
          ...'P5\n3 2\n255\n'.codeUnits,
          0,
          254,
          205,
          205,
          254,
          0,
        ]),
      );
      final ascii = parsePgm(
        Uint8List.fromList('P2\n2 2\n255\n0 254\n205 100\n'.codeUnits),
      );

      expect((binary.width, binary.height), (3, 2));
      expect(binary.cells, [0, 254, 205, 205, 254, 0]);
      expect(ascii.cells, [0, 254, 205, 100]);
    });

    test('skips comments and rejects malformed images', () {
      final withComment = parsePgm(
        Uint8List.fromList([...'P5\n# map\n2 1\n255\n'.codeUnits, 7, 9]),
      );
      expect(withComment.cells, [7, 9]);
      expect(
        () => parsePgm(
          Uint8List.fromList([...'P5\n10 10\n255\n'.codeUnits, 1, 2, 3]),
        ),
        throwsA(isA<SlamMapParseError>()),
      );
      expect(
        () => parsePgm(Uint8List.fromList('P6\n2 2\n255\n'.codeUnits)),
        throwsA(isA<SlamMapParseError>()),
      );
    });
  });

  test('detects map image formats from bytes rather than file names', () {
    expect(
      mapImageFormat(Uint8List.fromList('P5\n1 1\n255\n'.codeUnits)),
      MapImageFormat.pgm,
    );
    expect(
      mapImageFormat(Uint8List.fromList([0x89, 0x50, 0x4E, 0x47, 0, 0])),
      MapImageFormat.png,
    );
    expect(
      mapImageFormat(Uint8List.fromList([0x42, 0x4D, 0, 0])),
      MapImageFormat.bmp,
    );
    expect(
      mapImageFormat(Uint8List.fromList([0xFF, 0xD8, 0xFF, 0xE0])),
      MapImageFormat.jpeg,
    );
    expect(
      mapImageFormat(Uint8List.fromList('hello'.codeUnits)),
      MapImageFormat.unknown,
    );
  });

  test('suggests an origin by aligning map centers', () {
    final origin = suggestSlamOrigin(
      slamWidth: 100,
      slamHeight: 100,
      slamResolution: .02,
      referenceMinX: 0,
      referenceMinY: -3,
      referenceWidthMeters: 4,
      referenceHeightMeters: 3,
    );
    expect(origin.x, closeTo(1, 1e-9));
    expect(origin.y, closeTo(-2.5, 1e-9));
  });

  test('rewrites origin while preserving map data and YAML fields', () {
    final map = SlamMap(
      imageName: 'a_slam.pgm',
      width: 4,
      height: 3,
      resolution: .05,
      originX: -1.24,
      originY: -3.87,
      originYaw: 0,
      cells: Uint8List(12),
      freeThreshold: .25,
      negate: true,
    );

    final moved = map.withOrigin(1.5, -2.5);
    final yaml = moved.toYaml(note: 'adjusted');

    expect(moved.cells, hasLength(12));
    expect(yaml, contains('# adjusted'));
    expect(yaml, contains('image: a_slam.pgm'));
    expect(yaml, contains('origin: [1.500000, -2.500000, 0.000000]'));
    expect(yaml, contains('negate: 1'));
  });

  test('derives map bounds from origin, resolution, and cell count', () {
    final map = SlamMap(
      imageName: 'a.pgm',
      width: 100,
      height: 50,
      resolution: .05,
      originX: -1,
      originY: -2,
      originYaw: 0,
      cells: Uint8List(5000),
    );
    expect(map.bounds.minX, -1);
    expect(map.bounds.maxX, closeTo(4, 1e-9));
    expect(map.bounds.minY, -2);
    expect(map.bounds.maxY, closeTo(.5, 1e-9));
  });
}
