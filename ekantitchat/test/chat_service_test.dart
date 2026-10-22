import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:ekantitchat/chat_history_service.dart';
import 'package:ekantitchat/chat_service.dart';
import 'package:ekantitchat/chat_session.dart';

void main() {
  group('ChatMessage & MatchedEpisode Model Tests', () {
    test('ChatMessage serializes correctly for user and assistant', () {
      final userMsg = ChatMessage.user('What is seva?');
      expect(userMsg.isUser, isTrue);
      expect(userMsg.role, 'user');
      expect(userMsg.content, 'What is seva?');
      expect(userMsg.toHistoryMap(), {'role': 'user', 'content': 'What is seva?'});

      final botMsg = ChatMessage.assistant('Seva is devotion.', matchedEpisodes: [
        const MatchedEpisode(sourceFile: '#1363 Ekantik_2026.mp3', score: 0.88),
      ]);
      expect(botMsg.isUser, isFalse);
      expect(botMsg.role, 'assistant');
      expect(botMsg.content, 'Seva is devotion.');
      expect(botMsg.matchedEpisodes.length, 1);
      expect(botMsg.matchedEpisodes.first.displayTitle, '#1363 Ekantik');
      expect(botMsg.matchedEpisodes.first.formattedScore, '88%');
    });

    test('ChatResponse parses json properly', () {
      final json = {
        'answer': 'Radhe Radhe',
        'matched_episodes': [
          {'source_file': 'ep1.wav', 'score': 0.75}
        ],
        'standalone_query': 'What is meditation?'
      };

      final response = ChatResponse.fromJson(json);
      expect(response.answer, 'Radhe Radhe');
      expect(response.matchedEpisodes.length, 1);
      expect(response.matchedEpisodes.first.sourceFile, 'ep1.wav');
      expect(response.matchedEpisodes.first.score, 0.75);
      expect(response.standaloneQuery, 'What is meditation?');
    });

    test('ChatMessage toJson and fromJson round-trips correctly', () {
      final original = ChatMessage.assistant(
        'Vrindavan dham',
        matchedEpisodes: [
          const MatchedEpisode(sourceFile: 'ep100.mp3', score: 0.92),
        ],
      );
      final json = original.toJson();
      final restored = ChatMessage.fromJson(json);

      expect(restored.role, 'assistant');
      expect(restored.content, 'Vrindavan dham');
      expect(restored.isError, isFalse);
      expect(restored.matchedEpisodes.length, 1);
      expect(restored.matchedEpisodes.first.sourceFile, 'ep100.mp3');
      expect(restored.matchedEpisodes.first.score, 0.92);
    });
  });


  group('ChatService Tests', () {
    test('sendChat sends correct query and history payload', () async {
      String? sentBody;
      final mockClient = MockClient((request) async {
        if (request.url.path == '/chat' && request.method == 'POST') {
          sentBody = request.body;
          return http.Response(
            jsonEncode({
              'answer': 'Seva is divine.',
              'matched_episodes': [
                {'source_file': '#1363.mp3', 'score': 0.85}
              ],
              'standalone_query': 'Why is seva important?'
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final service = ChatService(
        baseUrl: 'http://test-server:8000',
        client: mockClient,
      );

      final history = [
        ChatMessage.user('What is seva?'),
        ChatMessage.assistant('Seva is selfless service.'),
        ChatMessage.assistant('Network error occurred', isError: true), // should be omitted from history
      ];

      final response = await service.sendChat(
        query: 'Why is it important?',
        history: history,
      );

      expect(response.answer, 'Seva is divine.');
      expect(response.matchedEpisodes.length, 1);
      expect(response.standaloneQuery, 'Why is seva important?');

      expect(sentBody, isNotNull);
      final decoded = jsonDecode(sentBody!) as Map<String, dynamic>;
      expect(decoded['query'], 'Why is it important?');

      final sentHistory = decoded['history'] as List<dynamic>;
      // The error message must be filtered out:
      expect(sentHistory.length, 2);
      expect(sentHistory[0]['role'], 'user');
      expect(sentHistory[0]['content'], 'What is seva?');
      expect(sentHistory[1]['role'], 'assistant');
      expect(sentHistory[1]['content'], 'Seva is selfless service.');
    });

    test('sendChat caps history to maxHistoryMessages', () async {
      String? sentBody;
      final mockClient = MockClient((request) async {
        sentBody = request.body;
        return http.Response(
          jsonEncode({'answer': 'OK', 'matched_episodes': []}),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      });

      final service = ChatService(
        baseUrl: 'http://test-server:8000',
        client: mockClient,
      );

      // Create 30 historical messages
      final largeHistory = List.generate(
        30,
        (i) => i.isEven ? ChatMessage.user('Q$i') : ChatMessage.assistant('A$i'),
      );

      await service.sendChat(query: 'Latest Q', history: largeHistory);

      final decoded = jsonDecode(sentBody!) as Map<String, dynamic>;
      final sentHistory = decoded['history'] as List<dynamic>;
      expect(sentHistory.length, ChatService.maxHistoryMessages);
      expect(sentHistory.last['content'], 'A29');
    });
  });

  group('ChatSession & History Model Tests', () {
    test('ChatSession serializes and deserializes properly', () {
      final now = DateTime.now();
      final session = ChatSession(
        id: 'sess-123',
        title: 'मन को शांत कैसे करें?',
        lastSnippet: 'Abhyasa aur Vairagya...',
        updatedAt: now,
        createdAt: now,
        messages: [
          ChatMessage.user('मन को शांत कैसे करें?'),
          ChatMessage.assistant('अभ्यास और वैराग्य से मन शांत होता है।'),
        ],
      );

      final json = session.toJson();
      final restored = ChatSession.fromJson(json);

      expect(restored.id, 'sess-123');
      expect(restored.title, 'मन को शांत कैसे करें?');
      expect(restored.lastSnippet, 'Abhyasa aur Vairagya...');
      expect(restored.messages.length, 2);
      expect(restored.messages.first.content, 'मन को शांत कैसे करें?');
    });

    test('ChatHistoryService formatDisplayDate handles today and yesterday', () {
      final now = DateTime.now();
      final todayStr = ChatHistoryService.formatDisplayDate(now);
      expect(todayStr, 'Today');

      final yesterday = now.subtract(const Duration(days: 1));
      final yesterdayStr = ChatHistoryService.formatDisplayDate(yesterday);
      expect(yesterdayStr, 'Yesterday');
    });
  });
}

