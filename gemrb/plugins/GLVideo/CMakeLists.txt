# SPDX-FileCopyrightText: 2026 Contributors to the GemRB project <https://gemrb.org>
#
# SPDX-License-Identifier: GPL-2.0-or-later

# OpenGL 3.3 core renderer on SDL2 (VideoDriver=opengl in GemRB.cfg)
IF(SDL_BACKEND STREQUAL "SDL2" AND NOT DISABLE_GL_VIDEO)
	FIND_PACKAGE(OpenGL)
	FIND_PACKAGE(GLEW)
	IF(OPENGL_FOUND AND GLEW_FOUND)
		IF(SDL2_SDL2main_FOUND)
			STRING(REPLACE "SDL2::SDL2main" "" GL_SDL_LIBRARY "${SDL_LIBRARY}")
		ELSE()
			SET(GL_SDL_LIBRARY "${SDL_LIBRARY}")
		ENDIF()
		ADD_GEMRB_PLUGIN(GLVideo GLVideo.cpp GLSprite2D.cpp
			../SDLVideo/GamepadControl.cpp ../SDLVideo/DPadSoftKeyboard.cpp)
		TARGET_INCLUDE_DIRECTORIES(GLVideo PRIVATE ${SDL_INCLUDE_DIR} ${GLEW_INCLUDE_DIRS})
		TARGET_LINK_LIBRARIES(GLVideo ${GL_SDL_LIBRARY} GLEW::GLEW ${OPENGL_LIBRARIES} Threads::Threads)
	ELSE()
		MESSAGE(STATUS "GLVideo plugin disabled: OpenGL or GLEW not found")
	ENDIF()
ENDIF()
