importScripts('https://www.gstatic.com/firebasejs/9.0.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/9.0.0/firebase-messaging-compat.js');

const firebaseConfig = {
  apiKey: "AIzaSyDRpv8BvnEYVimozbvfNxJWlhAtMqf7ZWs",
  authDomain: "garudaltell.firebaseapp.com",
  projectId: "garudaltell",
  storageBucket: "garudaltell.firebasestorage.app",
  messagingSenderId: "528124989420",
  appId: "1:528124989420:web:b4b3677c568566808d3ac9"
};

firebase.initializeApp(firebaseConfig);
const messaging = firebase.messaging();

// Menangani notifikasi saat aplikasi di background
messaging.onBackgroundMessage(function(payload) {
  console.log('[sw.js] Notifikasi Background:', payload);
  const notificationTitle = payload.notification.title;
  const notificationOptions = {
    body: payload.notification.body,
    icon: '/static/img/logo.png'
  };
  return self.registration.showNotification(notificationTitle, notificationOptions);
});
